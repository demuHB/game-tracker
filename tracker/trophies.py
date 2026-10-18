"""Trophäen-Überwachung über Exophase.

Exophase entdeckt neue Trophäen-/Erfolgslisten selbstständig, oft schon vor Release (mit 0 Spielern).
Einmal täglich wird jedes Spiel mit PlayStation, PC oder Xbox im Tracker per Name gesucht – zuerst die
PlayStation-Liste, sonst Steam, sonst Xbox (die Erfolge sind dort bis auf Platin gleich und tauchen oft
früher auf). Meldung, wenn erstmals eine Liste auftaucht, wenn später die PlayStation-Liste dazukommt
oder wenn die Anzahl steigt (DLC).

Vor Release sind Listen oft noch vorläufig (Platzhalter wie „NEW_ACHIEVEMENT_DESC_1_3“ oder nur Japanisch).
Darum wird jede Liste anhand ihrer Trophäennamen bewertet (Deutsch > Englisch > andere Sprache > Platzhalter);
die beste Liste gewinnt – erst nach Sprache, dann nach Plattform – und eine Verbesserung wird erneut gemeldet.
"""
import html
import re
import logging
import time
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import quote_plus

import requests

from . import config, igdb
from .models import days_until, has_achievements, title

log = logging.getLogger(__name__)

SEARCH_URL = 'https://api.exophase.com/public/archive/platform/{platform}/page/1'
PLATFORMS = ['psn', 'steam', 'xbox']           # Reihenfolge = Vorrang
PLATFORM_NAMES = {'psn': 'PlayStation', 'steam': 'Steam', 'xbox': 'Xbox'}
HEADERS = {'User-Agent': f'GameReleaseTracker/{config.APP_VERSION} (privat)'}
IGNORE = '-'          # exophase_id-Wert für "falscher Treffer, ignorieren"
MIN_RATIO = 0.92

# Sprachstufen der Trophäenliste (höher = besser)
PLACEHOLDER, OTHER_LANGUAGE, ENGLISH, GERMAN = 0, 1, 2, 3
UNRATED = -1
LANGUAGE_LABELS = {PLACEHOLDER: 'Platzhalter', OTHER_LANGUAGE: 'andere Sprache', ENGLISH: 'Englisch', GERMAN: 'Deutsch'}

_PLACEHOLDER_RE = re.compile(
    r'^\s*$|NEW_?ACHIEVEMENT|_(NAME|DESC)_|^ACH(IEVEMENT)?[_ ]?\d+|^(achievement|trophy|trophäe|troph[eé]e)\s*#?\d+$'
    r'|^\s*(test|tbd|tba|placeholder|todo|dummy)\b|^#\w+',
    re.IGNORECASE)
# Steam setzt „[english]“ o.Ä. vor Texte, deren Übersetzung fehlt – der Rest ist dann die Originalsprache
_LANG_MARKER_RE = re.compile(r'\[[a-z]+\]\s*', re.IGNORECASE)
_NON_LATIN_RE = re.compile(r'[\u0400-\u04ff\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\u0e00-\u0e7f\u0600-\u06ff]')
_WORD_RE = re.compile(r"[a-zäöüß']+", re.IGNORECASE)
_GERMAN = {'der', 'die', 'das', 'und', 'ein', 'eine', 'einen', 'mit', 'für', 'auf', 'alle', 'allen', 'nicht', 'den',
           'dem', 'des', 'im', 'zu', 'von', 'du', 'dein', 'deine', 'besiege', 'besiegt', 'erhalte', 'erhalten',
           'schließe', 'abgeschlossen', 'sammle', 'gesammelt', 'finde', 'gefunden', 'kapitel', 'spiel', 'ist', 'wurde'}
_ENGLISH = {'the', 'of', 'and', 'a', 'an', 'to', 'in', 'all', 'your', 'you', 'with', 'for', 'on', 'complete',
            'completed', 'defeat', 'defeated', 'obtain', 'obtained', 'collect', 'collected', 'find', 'found', 'unlock',
            'unlocked', 'chapter', 'reach', 'win', 'get', 'earn', 'every', 'first', 'without'}


def rate_language(entries):
    """Bewertet eine Trophäenliste [(Titel, Beschreibung), …] → (Stufe, Label) oder (UNRATED, '') ohne Einträge."""
    if not entries:
        return UNRATED, ''
    entries = [(_LANG_MARKER_RE.sub('', t or ''), _LANG_MARKER_RE.sub('', d or '')) for t, d in entries]
    placeholders = sum(1 for t, d in entries if _PLACEHOLDER_RE.search(t or '') or _PLACEHOLDER_RE.search(d or ''))
    if placeholders / len(entries) >= 0.3:
        return PLACEHOLDER, LANGUAGE_LABELS[PLACEHOLDER]
    text = ' '.join(f"{t} {d}" for t, d in entries)
    letters = [c for c in text if c.isalpha()]
    if letters and sum(1 for c in letters if _NON_LATIN_RE.match(c)) / len(letters) > 0.3:
        return OTHER_LANGUAGE, LANGUAGE_LABELS[OTHER_LANGUAGE]
    words = [w.lower() for w in _WORD_RE.findall(text)]
    de = sum(1 for w in words if w in _GERMAN) + sum(2 for w in words if any(c in w for c in 'äöüß'))
    en = sum(1 for w in words if w in _ENGLISH)
    if de >= 3 and de > en:
        return GERMAN, LANGUAGE_LABELS[GERMAN]
    if en >= 2:
        return ENGLISH, LANGUAGE_LABELS[ENGLISH]
    return OTHER_LANGUAGE, LANGUAGE_LABELS[OTHER_LANGUAGE]


_TIPPY_RE = re.compile(r'data-tippy-content="([^"]*)"')
_TIPPY_PARTS_RE = re.compile(r'<strong>(.*?)</strong>\s*(?:<p>(.*?)</p>)?', re.S)


def parse_awards(page_html):
    """Titel/Beschreibung aller Einträge einer Exophase-Listenseite."""
    entries = []
    for raw in _TIPPY_RE.findall(page_html):
        match = _TIPPY_PARTS_RE.search(html.unescape(raw))
        if match:
            entries.append((html.unescape(match.group(1) or '').strip(), html.unescape(match.group(2) or '').strip()))
    return entries


def quality_note(quality):
    """Zusatz für Meldungen bei vorläufigen Listen."""
    if quality == PLACEHOLDER:
        return " · noch Platzhalter"
    if quality == OTHER_LANGUAGE:
        return " · andere Sprache"
    return ""


def _normalize(name):
    """Wie igdb.normalize_name, entfernt zusätzlich Akzente ('Yōtei' → 'yotei')."""
    ascii_name = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode()
    return igdb.normalize_name(ascii_name)


def is_match(a, b):
    na, nb = _normalize(a), _normalize(b)
    return bool(na) and (na == nb or SequenceMatcher(None, na, nb).ratio() >= MIN_RATIO)


def _platform_rank(entry):
    names = [p.get('name', '') for p in entry.get('platforms') or []]
    return 2 if 'PS5' in names else 1 if 'PS4' in names else 0


def award_label(platform, count):
    """'35 Trophäen' (PlayStation) bzw. '35 Erfolge (Steam)'."""
    if platform in ('', 'psn'):
        return f"{count} {'Trophäe' if count == 1 else 'Trophäen'}"
    return f"{count} {'Erfolg' if count == 1 else 'Erfolge'} ({PLATFORM_NAMES.get(platform, platform)})"


def psnprofiles_url(game):
    """Hinterlegter PSNProfiles-Link oder die Suche nach dem Spiel – wird nur im Browser der User geöffnet, nie
    automatisch abgefragt (PSNProfiles blockt automatische Abrufe per Cloudflare)."""
    return game.get('psnprofiles_link') or f"https://psnprofiles.com/search/games?q={quote_plus(title(game))}"


def trophy_link(game):
    """Ziel des 🏆-Abzeichens: von Hand hinterlegter PSNProfiles-Link, sonst die gefundene Exophase-Liste."""
    return game.get('psnprofiles_link') or game.get('exophase_url') or ''


def is_psnprofiles_link(url):
    return url.startswith(('https://psnprofiles.com/', 'http://psnprofiles.com/', 'https://www.psnprofiles.com/'))


def stored_platform(game):
    """Plattform der gespeicherten Liste; ältere Einträge (vor Steam/Xbox) stammen immer von PlayStation."""
    if game.get('exophase_platform'):
        return game['exophase_platform']
    return 'psn' if game.get('exophase_id') not in ('', None, IGNORE) else ''


class ExophaseMonitor:
    def __init__(self, store):
        self.store = store
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def search(self, platform, query):
        response = self.session.get(SEARCH_URL.format(platform=platform), params={'q': query, 'sort': 'added'},
                                    timeout=15)
        response.raise_for_status()
        games = response.json().get('games')
        return games.get('list', []) if isinstance(games, dict) else []

    def fetch_awards(self, url):
        response = self.session.get(url, timeout=20, headers={'Accept': 'text/html'})
        response.raise_for_status()
        return parse_awards(response.text)

    def _find_on(self, platform, names, known_id):
        """Bester Eintrag auf einer Plattform (gespeicherte ID bevorzugt) oder None."""
        for name in names:
            results = self.search(platform, name)
            time.sleep(1.5)
            if known_id:
                hit = next((r for r in results if str(r.get('master_id')) == known_id), None)
                if hit:
                    return hit
            candidates = [r for r in results if any(is_match(r.get('title', ''), n) for n in names)]
            if candidates:
                return max(candidates, key=lambda r: (_platform_rank(r), r.get('total_awards', 0)))
        return None

    def find(self, game):
        """Beste Liste: (Eintrag, Plattform, Sprachstufe, Label) – nach Sprache, dann PlayStation > Steam > Xbox.

        Kein Treffer → (None, None, UNRATED, '').
        """
        known_id = game.get('exophase_id')
        known_platform = stored_platform(game)
        known_quality = game.get('exophase_quality', UNRATED)
        names = list(dict.fromkeys(n for n in (game.get('name'), game.get('display_name')) if n))
        # schon die bestmögliche Art Liste (PlayStation, Deutsch/Englisch)? Dann nur noch dort nach DLC schauen
        settled = known_platform == 'psn' and known_quality >= ENGLISH and known_id
        found = []
        for platform in (['psn'] if settled else PLATFORMS):
            entry = self._find_on(platform, names, known_id if platform == known_platform else None)
            if not entry:
                continue
            count = int(entry.get('total_awards') or 0)
            same_list = str(entry.get('master_id')) == known_id and platform == known_platform
            if same_list and known_quality >= ENGLISH and count == int(game.get('psn_trophy_count') or 0):
                quality = known_quality   # unverändert und schon brauchbar – Seite nicht erneut laden
            else:
                try:
                    quality, _ = rate_language(self.fetch_awards(entry.get('endpoint_awards', '')))
                except Exception as e:
                    log.warning("Exophase-Liste %s nicht lesbar: %s", entry.get('endpoint_awards'), e)
                    quality = known_quality if same_list else UNRATED
                time.sleep(1.5)
            found.append((entry, platform, quality))
        if not found:
            return None, None, UNRATED, ''
        entry, platform, quality = max(found, key=lambda f: (f[2], -PLATFORMS.index(f[1])))
        return entry, platform, quality, LANGUAGE_LABELS.get(quality, '')

    def check_all(self):
        """Prüft alle Spiele mit PS/PC/Xbox; gibt Meldungstexte für das Popup zurück."""
        messages = []
        changed = False

        def notify(title_text, text, name):
            self.store.add_notification(title_text, text, "trophy_added", name)
            messages.append(f"🏆 {text}")

        for game in self.store.snapshot():
            if not has_achievements(game) or game.get('exophase_id') == IGNORE:
                continue
            try:
                entry, platform, quality, language = self.find(game)
            except Exception as e:
                log.warning("Exophase-Abfrage für %s fehlgeschlagen: %s", game['name'], e)
                continue
            if not entry:
                continue

            count = int(entry.get('total_awards') or 0)
            old_count = int(game.get('psn_trophy_count') or 0)
            old_platform = stored_platform(game)
            old_quality = game.get('exophase_quality', UNRATED)
            new_id = str(entry.get('master_id', ''))
            name = title(game)
            days = days_until(game.get('release_date'))
            already_out = days is not None and days < 0

            if old_count == 0 and count > 0:
                if not already_out:   # Ersterfassung bereits erschienener Spiele nur speichern
                    notify("🏆 Trophäenliste verfügbar",
                           f"{name}: Liste ist da – {award_label(platform, count)}{quality_note(quality)}", name)
            elif old_quality == UNRATED:
                pass   # erste Bewertung einer schon bekannten Liste (Update auf diese Version) – still
            elif quality > old_quality:
                if not already_out:
                    better = (f"jetzt auf {language}" if quality >= ENGLISH else "jetzt mit echten Namen")
                    notify("🏆 Trophäenliste aktualisiert",
                           f"{name}: Trophäen {better} – {award_label(platform, count)}{quality_note(quality)}", name)
            elif platform == 'psn' and old_platform not in ('', 'psn'):
                # vorher nur Steam/Xbox: kein „+1“ wegen Platin, sondern eigener Hinweis
                if not already_out:
                    notify("🎮 PlayStation-Liste jetzt auch da", f"{name}: PlayStation-Trophäenliste ist jetzt auch da "
                                                                 f"({count} Trophäen)", name)
            elif platform == old_platform and new_id == game.get('exophase_id') and count > old_count:
                notify("🏆 Neue Trophäen", f"{name}: +{count - old_count} – jetzt {award_label(platform, count)}", name)

            fields = {
                'exophase_id': str(entry.get('master_id', '')),
                'exophase_title': entry.get('title', ''),
                'exophase_url': entry.get('endpoint_awards', ''),
                'exophase_platform': platform,
                'exophase_quality': quality,
                'exophase_language': language,
                'psn_trophy_count': count,
            }
            if any(game.get(k) != v for k, v in fields.items()):
                with self.store.lock:
                    current = self.store.find(game['uid'])
                    if current:
                        current.update(fields)
                        changed = True

        if changed:
            self.store.save_games()
        return messages
