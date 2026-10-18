# Game Release Tracker

Tray-App für kommende Spiele-Releases: Countdown, IGDB-Cover, Release-Erinnerungen, Warteliste,
Trophäen-Benachrichtigungen über Exophase und eine Handy-Ansicht (PWA), synchronisiert über ein GitHub-Gist.
Die App aktualisiert sich selbst aus den GitHub-Releases dieses Repos.

## Einmalige Einrichtung auf dem Ziel-PC

1. Einen Ordner anlegen, z.B. `C:\Tools\GameTracker\`.
2. `GameTracker.exe` aus dem **neuesten Release** dieses Repos herunterladen:
   https://github.com/demuHB/game-tracker/releases/latest
3. Diese Dateien von der alten Installation **neben die exe** legen:
   `games.json`, `config.json`, `waitlist.json`, `notifications.json`.
   **`config.json` muss die Zugangsdaten enthalten** (`igdb_client_id`, `igdb_client_secret`, `github_token`).
   Fehlt einer, zeigt die App beim Start einen Hinweis.
4. Die **alte Version 1.8 beenden** und aus dem Autostart entfernen. Sonst überschreibt sie das Gist
   mit ihrer Liste ohne Cover-IDs.
5. `GameTracker.exe` starten. Das Icon erscheint im Tray (evtl. unter dem „^“-Pfeil).
6. Autostart: `Win+R` → `shell:startup` → dort eine Verknüpfung zu `GameTracker.exe` ablegen.

Neben der exe legt die App `covers\` (Cover-Cache) und `gametracker.log` (Protokoll für die Fehlersuche) an.

## Updates

Nichts zu tun: Die App prüft beim Start und alle 6 Stunden, ob es ein neueres Release gibt,
lädt es herunter, startet sich kurz neu und meldet „Aktualisiert auf Version X“.
Ist gerade ein Dialog offen, wartet sie, bis du ihn schließt.

So entsteht eine neue Version: Ein Push auf `main`, der App-Dateien betrifft (`tracker/`, `gametracker.pyw`,
`requirements.txt`, `GameTracker.spec`, `icon.ico`), baut automatisch eine neue exe und ein Release
(GitHub Actions, ca. 3–5 Minuten).

## Handy-Ansicht (PWA)

https://demuhb.github.io/game-tracker/ – wird aus dem Ordner `docs/` per GitHub Pages ausgeliefert
und ist etwa 1 Minute nach jedem Push aktuell.
Die Spieleliste kommt aus dem Gist, das die Desktop-App bei jeder Änderung aktualisiert.

## Ansichten

- **📅 Mit Datum / ⏳ Ohne Datum / 🗄 Archiv** – drei Tabs in der Spieleliste und in der PWA.
- **Ohne Datum:** Kennt IGDB nur ein Jahr, Quartal oder einen Monat, steht dort „📆 2027“ bzw. „📆 Q4 2027“ statt
  eines Platzhalter-Datums. Wird der Termin genauer, kommt eine Benachrichtigung.
- **Archiv:** Erschienene Spiele über das „🗄 Archivieren“-Abzeichen auf der Karte oder den Knopf im Bearbeiten-Dialog
  archivieren. Archivierte Spiele bekommen keine IGDB-Updates mehr, ihre Trophäen werden aber weiter geprüft (DLC).
- **Jahres-Ansicht:** Der kleine Schalter „Jahre“ unten rechts (PWA: „nach Jahren“) trennt die Listen nach Jahren.

## Sicherungen

Die App legt täglich eine Kopie von `games.json`, `waitlist.json` und `notifications.json` unter `backups\JJJJ-MM-TT\`
an und behält die letzten 7 Tage. Zum Wiederherstellen die App beenden und die Dateien zurückkopieren.

## Trophäen-Benachrichtigungen

Einmal täglich sucht die App jedes Spiel mit PlayStation, PC oder Xbox auf Exophase – zuerst die
PlayStation-Liste, sonst die Steam- und dann die Xbox-Liste (die Erfolge sind bis auf Platin gleich und
tauchen oft früher auf). Exophase entdeckt neue Listen meist schon vor Release. Du wirst benachrichtigt,
wenn eine Liste erstmals auftaucht, wenn später die PlayStation-Liste dazukommt oder wenn Trophäen
dazukommen (DLC). Kein Token nötig.
Vor Release sind Listen oft vorläufig (Platzhalter-Namen oder nur Japanisch o.Ä.). Die App liest dafür die
Trophäennamen und wählt die beste Liste – zuerst nach Sprache (Deutsch > Englisch > andere Sprache > Platzhalter),
dann nach Plattform. Wird eine Liste brauchbar, kommt eine zweite Meldung („Trophäen jetzt auf Englisch“).
Vorläufige Listen haben ein blasses 🏆. Hinweis: Exophase zeigt Listen fast immer auf Englisch.
Im Bearbeiten-Dialog: **Jetzt prüfen**, **Falscher Treffer** (ignoriert den Treffer), **↗** öffnet die Liste auf Exophase.

## Entwicklung

```
pip install -r requirements.txt
python gametracker.pyw --show
```

- `GAMETRACKER_DATA_DIR=<Ordner>`: Testdaten aus einem anderen Ordner verwenden
- `GAMETRACKER_NO_CLOUD=1`: kein Upload ins Gist (sonst landet jede Teständerung auf dem Handy)
- `GAMETRACKER_UPDATE_URL=<Pfad/URL>`: alternative Release-Info (zum Testen des Self-Updates)
- Exe lokal bauen: `build.bat` → `release\GameTracker.exe` (Version `0.0.0-dev`, aktualisiert sich nie selbst)

Persönliche Daten und `config.json` stehen in `.gitignore` und dürfen nie ins Repo.

| Datei | Zweck |
|---|---|
| `gametracker.pyw` | Einstiegspunkt (Logging, Einzelinstanz) |
| `tracker/config.py` | Konstanten; liest die Zugangsdaten aus `config.json` |
| `tracker/storage.py` | JSON laden/speichern (thread-safe, atomar) |
| `tracker/igdb.py` | IGDB-Suche, ID-Abfrage, Namensvergleich |
| `tracker/updater.py` | Tägliches Update, Erinnerungen, Warteliste, Cover nachladen |
| `tracker/trophies.py` | Trophäen-Überwachung über Exophase |
| `tracker/selfupdate.py` | Self-Update aus GitHub-Releases |
| `tracker/cloud.py` | Gist-Upload |
| `tracker/covers.py` | Cover-Download/-Cache |
| `tracker/ui/` | CustomTkinter-Oberfläche (`app.py` = ein einziger Tk-Root plus Task-Queue) |
| `docs/` | PWA (GitHub Pages) |
| `.github/workflows/release.yml` | Automatischer Exe-Build + Release |
