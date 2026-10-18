"""Datenmodell-Helfer für Spiele (dicts, kompatibel zum bestehenden games.json)."""
import re
import uuid
from datetime import datetime

GAME_DEFAULTS = {
    'name': '',
    'display_name': '',
    'release_date': '',
    'release_window': '',      # ungenauer Termin laut IGDB: „2027“, „Q2 2027“, „März 2027“ – leer = Tagesdatum
    'platforms': '',
    'rating': 0,
    'hyped': False,
    'manual_tba': False,
    'last_known_date': '',
    'igdb_id': '',
    'cover_id': '',
    'psn_trophy_count': 0,
    'exophase_id': '',
    'exophase_title': '',
    'exophase_url': '',
    'exophase_platform': '',   # psn / steam / xbox
    'exophase_quality': -1,    # Sprachstufe der Liste: -1 unbewertet, 0 Platzhalter, 1 andere Sprache, 2 Englisch, 3 Deutsch
    'exophase_language': '',
    'archived': False,         # im Archiv: nicht mehr in der Hauptliste, Trophäen werden weiter geprüft
    'archived_at': '',
}


def new_uid():
    return uuid.uuid4().hex[:12]


def normalize_game(game):
    """Ergänzt fehlende Felder und vereinheitlicht Typen."""
    for key, value in GAME_DEFAULTS.items():
        if key not in game or game[key] is None:
            game[key] = value
    game['igdb_id'] = str(game['igdb_id']) if game['igdb_id'] not in ('', None) else ''
    if not game.get('uid'):
        game['uid'] = new_uid()
    return game


def make_game(result, hyped=False, manual_tba=False):
    """Erzeugt ein Spiel aus einem IGDB-Ergebnis-dict.

    manual_tba: das IGDB-Datum ist nur ein Platzhalter → Spiel landet unter „Ohne Datum“,
    das Datum wird als last_known_date gemerkt (wie beim Häkchen im Bearbeiten-Dialog).
    """
    release_date = format_date_european(result.get('release_date', ''))
    return normalize_game({
        'name': result.get('name', ''),
        'release_date': release_date,
        'release_window': result.get('release_window', ''),
        'manual_tba': manual_tba,
        'last_known_date': release_date if manual_tba else '',
        'platforms': result.get('platforms', ''),
        'rating': result.get('rating', 0),
        'igdb_id': result.get('igdb_id', ''),
        'cover_id': result.get('cover_id', ''),
        'hyped': hyped,
    })


def title(game):
    return game.get('display_name') or game.get('name', '')


def parse_date(date_str):
    if not date_str:
        return None
    for fmt in ('%d.%m.%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            pass
    return None


def format_date_european(date_str):
    """YYYY-MM-DD → DD.MM.YYYY (andere Formate unverändert)."""
    if not date_str or '.' in date_str:
        return date_str or ''
    parsed = parse_date(date_str)
    return parsed.strftime('%d.%m.%Y') if parsed else date_str


def days_until(date_str):
    release = parse_date(date_str)
    if not release:
        return None
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return (release - today).days


def days_between(game1, game2):
    d1, d2 = parse_date(game1.get('release_date')), parse_date(game2.get('release_date'))
    if d1 and d2:
        return abs((d2 - d1).days)
    return None


def is_tba(game):
    """Kein genaues Datum: von Hand als Platzhalter markiert, gar kein Datum oder nur Jahr/Quartal/Monat bekannt."""
    return bool(game.get('manual_tba') or not game.get('release_date') or game.get('release_window'))


def release_year(game):
    """Jahr für die Jahres-Ansicht (aus Datum, Zeitraum oder Platzhalter) – None, wenn unbekannt."""
    match = re.search(r'(\d{4})', game.get('release_window') or '')
    if match:
        return int(match.group(1))
    parsed = parse_date(game.get('release_date') or game.get('last_known_date'))
    return parsed.year if parsed else None


def sort_key_archive(game):
    """Archiv: zuletzt erschienene zuerst (für sorted(..., reverse=True))."""
    parsed = parse_date(game.get('release_date'))
    return parsed.strftime('%Y-%m-%d') if parsed else '0000-00-00'


def has_achievements(game):
    """Plattform mit Trophäen/Erfolgen: PlayStation, PC (Steam) oder Xbox – reine Switch-Spiele haben keine."""
    platforms = (game.get('platforms') or '').lower()
    return any(p in platforms for p in ('playstation', 'pc', 'windows', 'xbox', 'steam'))


def format_weeks(days):
    rounded = round(days / 7 * 2) / 2
    return f"{int(rounded) if rounded == int(rounded) else rounded} Wochen"


def platform_list(platforms_str):
    """Xbox raus, PC kürzen, Switch-Redundanz raus, sortiert PS5 → Switch 2 → PC → Rest."""
    if not platforms_str:
        return []

    cleaned = []
    for p in (p.strip() for p in platforms_str.split(',')):
        if not p:
            continue
        low = p.lower()
        if 'xbox' in low:
            continue
        if 'microsoft windows' in low:
            p = 'PC'
        if p not in cleaned:
            cleaned.append(p)

    if any('switch 2' in p.lower() for p in cleaned):
        cleaned = [p for p in cleaned if not (p.lower().endswith('switch') and 'switch 2' not in p.lower())]

    def sort_key(name):
        n = name.lower()
        if 'playstation 5' in n:
            return (0, name)
        if 'switch 2' in n:
            return (1, name)
        if n == 'pc':
            return (2, name)
        return (3, name)

    return sorted(cleaned, key=sort_key)


PLATFORM_SHORT = {
    'PlayStation 5': 'PS5',
    'PlayStation 4': 'PS4',
    'PlayStation 3': 'PS3',
    'Nintendo Switch 2': 'Switch 2',
    'Nintendo Switch': 'Switch',
    'PlayStation VR2': 'PS VR2',
    'Google Stadia': 'Stadia',
}


def short_platform(name):
    return PLATFORM_SHORT.get(name, name)


def sort_key_dated(game):
    parsed = parse_date(game.get('release_date'))
    return parsed.strftime('%Y-%m-%d') if parsed and not is_tba(game) else '9999-12-31'


def sort_key_tba(game):
    parsed = parse_date(game.get('last_known_date') or game.get('release_date'))
    return (0, parsed.strftime('%Y-%m-%d')) if parsed else (1, '9999-12-31')
