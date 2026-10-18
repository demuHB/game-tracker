"""Spiel bearbeiten."""
import threading
import webbrowser
from datetime import datetime

import customtkinter as ctk

from ..trophies import (IGNORE, OTHER_LANGUAGE, PLACEHOLDER, PLATFORM_NAMES, UNRATED, award_label,
                        psnprofiles_url, stored_platform)
from ..models import has_achievements, title
from . import theme
from .widgets import ScrollFrame, BaseWindow, ConfirmDialog, add_context_menu, chip_row, countdown_info, Pill

COVER = (96, 128)


class EditDialog(BaseWindow):
    def __init__(self, app, uid, on_close=None):
        self.uid = uid
        game = app.store.find(uid)
        super().__init__(app, f"Bearbeiten: {title(game)}", 720, 720, on_close=on_close, maximized=True)
        self.game = dict(game)

        # --- Kopf mit Cover ---
        head = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=0)
        head.pack(fill='x')
        self.cover = ctk.CTkLabel(head, text='')
        self.cover.pack(side='left', padx=20, pady=16)
        self._set_cover()
        info = ctk.CTkFrame(head, fg_color='transparent')
        info.pack(side='left', fill='both', expand=True, pady=16, padx=(0, 20))
        hyped = self.game.get('hyped')
        ctk.CTkLabel(info, text=('★ ' if hyped else '') + title(self.game), font=theme.H1,
                     text_color=theme.GOLD if hyped else theme.TEXT, anchor='w', justify='left',
                     wraplength=520).pack(fill='x')
        if self.game.get('display_name'):
            ctk.CTkLabel(info, text=f"IGDB: {self.game['name']}", font=theme.SMALL, text_color=theme.MUTED,
                         anchor='w').pack(fill='x')
        chips = chip_row(info, self.game.get('platforms'), theme.SURFACE)
        if chips:
            chips.pack(anchor='w', pady=(8, 0))
        text, colors, outline = countdown_info(self.game)
        Pill(info, text, colors, outline=outline).pack(anchor='w', pady=(8, 0))
        if self.game.get('psn_trophy_count'):
            Pill(info, f"🏆 {self.game['psn_trophy_count']} Trophäen",
                 ('#1b2f4d', theme.TROPHY)).pack(anchor='w', pady=(6, 0))

        # --- Buttons unten ---
        buttons = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=0)
        buttons.pack(fill='x', side='bottom')
        ctk.CTkButton(buttons, text="💾  Speichern", width=140, command=self.save,
                      **theme.button_style('success')).pack(side='right', padx=(6, 20), pady=12)
        ctk.CTkButton(buttons, text="Abbrechen", width=110, command=self.close,
                      **theme.button_style('ghost')).pack(side='right', pady=12)
        ctk.CTkButton(buttons, text="🗑  Löschen", width=110, command=self.confirm_delete,
                      **theme.button_style('danger')).pack(side='left', padx=(20, 6), pady=12)
        archived = self.game.get('archived')
        ctk.CTkButton(buttons, text="↩  Aus Archiv holen" if archived else "🗄  Archivieren", width=150,
                      command=self.toggle_archive, **theme.button_style('subtle')).pack(side='left', pady=12)

        # --- Formular ---
        form = ScrollFrame(self, fg_color='transparent')
        form.pack(fill='both', expand=True, padx=12, pady=8)
        form.grid_columnconfigure((0, 1), weight=1, uniform='col')

        self.display_name = self._field(form, 0, 0, "Anzeigename", self.game.get('display_name'),
                                        "leer = Originalname")
        self.release_date = self._field(form, 0, 1, "Release-Datum", self.game.get('release_date'),
                                        "TT.MM.JJJJ – leer = unbekannt")
        self.platforms = self._field(form, 1, 0, "Plattformen", self.game.get('platforms'),
                                     "kommagetrennt (wird bei Updates von IGDB überschrieben)", colspan=2)
        self.igdb_id = self._field(form, 2, 0, "IGDB-ID", self.game.get('igdb_id'),
                                   "bestimmt das Spiel eindeutig – nur ändern, wenn falsch")

        # Trophäen (Exophase)
        self.trophy_fields = {}  # vorgemerkte Änderungen, werden mit „Speichern" übernommen
        box = ctk.CTkFrame(form, fg_color='transparent')
        box.grid(row=2, column=1, sticky='nsew', padx=8, pady=6)
        ctk.CTkLabel(box, text="Trophäen (Exophase)", font=theme.SMALL_BOLD, text_color=theme.MUTED,
                     anchor='w').pack(fill='x')
        self.trophy_status = ctk.CTkLabel(box, text="", font=theme.SMALL, text_color=theme.TEXT, anchor='w',
                                          justify='left', wraplength=300)
        self.trophy_status.pack(fill='x', pady=(4, 4))
        row = ctk.CTkFrame(box, fg_color='transparent')
        row.pack(fill='x')
        small = {**theme.button_style('subtle'), 'height': 28, 'font': theme.SMALL_BOLD}
        self.check_btn = ctk.CTkButton(row, text="Jetzt prüfen", width=100, command=self.check_trophies, **small)
        self.check_btn.pack(side='left')
        self.wrong_btn = ctk.CTkButton(row, text="Falscher Treffer", width=120, command=self.ignore_match, **small)
        self.wrong_btn.pack(side='left', padx=(6, 0))
        links = ctk.CTkFrame(box, fg_color='transparent')
        links.pack(fill='x', pady=(6, 0))
        self.psnp_btn = ctk.CTkButton(links, text="PSNProfiles ↗", width=120, command=self.open_psnprofiles, **small)
        self.psnp_btn.pack(side='left')
        self.open_btn = ctk.CTkButton(links, text="Exophase ↗", width=100, command=self.open_exophase, **small)
        self.open_btn.pack(side='left', padx=(6, 0))
        self._update_trophy_status()

        # Schalter
        switches = ctk.CTkFrame(form, fg_color=theme.SURFACE, corner_radius=theme.RADIUS)
        switches.grid(row=3, column=0, columnspan=2, sticky='ew', padx=8, pady=(14, 6))
        self.hyped = ctk.BooleanVar(value=self.game.get('hyped', False))
        ctk.CTkSwitch(switches, text="★  Besonders gehypt", variable=self.hyped, font=theme.BODY_BOLD,
                      text_color=theme.GOLD, progress_color=theme.HYPE_BORDER).pack(anchor='w', padx=16, pady=(14, 4))
        self.manual_tba = ctk.BooleanVar(value=self.game.get('manual_tba', False))
        ctk.CTkSwitch(switches, text="Datum ist nur ein Platzhalter (als TBA behandeln)", variable=self.manual_tba,
                      font=theme.BODY_BOLD, text_color=theme.TEXT, progress_color=theme.DANGER_DARK
                      ).pack(anchor='w', padx=16, pady=(8, 0))
        ctk.CTkLabel(switches, text="Das Spiel wandert in „Ohne Datum“. Wird automatisch aufgehoben, "
                                    "sobald IGDB ein neues Datum liefert.",
                     font=theme.TINY, text_color=theme.SUBTLE, anchor='w', justify='left', wraplength=600
                     ).pack(anchor='w', padx=62, pady=(0, 14))

        self.error = ctk.CTkLabel(form, text="", font=theme.SMALL_BOLD, text_color=theme.DANGER, anchor='w')
        self.error.grid(row=4, column=0, columnspan=2, sticky='ew', padx=8)

        self.bind('<Return>', lambda e: self.save())

    def _set_cover(self):
        if self.winfo_exists():
            self.cover.configure(image=self.app.covers.get(self.game.get('cover_id'), COVER, title(self.game),
                                                           on_ready=self._set_cover))

    def _field(self, parent, row, col, label, value, hint, colspan=1):
        box = ctk.CTkFrame(parent, fg_color='transparent')
        box.grid(row=row, column=col, columnspan=colspan, sticky='nsew', padx=8, pady=6)
        ctk.CTkLabel(box, text=label, font=theme.SMALL_BOLD, text_color=theme.MUTED, anchor='w').pack(fill='x')
        entry = add_context_menu(ctk.CTkEntry(box, **theme.entry_style()))
        if value:
            entry.insert(0, str(value))
        entry.pack(fill='x')
        ctk.CTkLabel(box, text=hint, font=theme.TINY, text_color=theme.SUBTLE, anchor='w').pack(fill='x')
        return entry

    # ------------------------------------------------------------- Aktionen
    def _trophy_value(self, key):
        return self.trophy_fields.get(key, self.game.get(key))

    def _update_trophy_status(self, override=None):
        exo_id = self._trophy_value('exophase_id')
        if not has_achievements(self.game):
            text, color = "Kein PlayStation-, PC- oder Xbox-Spiel", theme.SUBTLE
        elif override:
            text, color = override
        elif exo_id == IGNORE:
            text, color = "Treffer ignoriert – „Jetzt prüfen“ sucht neu", theme.SUBTLE
        elif exo_id:
            platform = self._trophy_value('exophase_platform') or stored_platform(self.game)
            language = self._trophy_value('exophase_language')
            text = (f"🏆 {award_label(platform, self._trophy_value('psn_trophy_count'))}"
                    f"{f' · {language}' if language else ''}\n"
                    f"{PLATFORM_NAMES.get(platform, 'Exophase')}: {self._trophy_value('exophase_title')}")
            preliminary = (self._trophy_value('exophase_quality') or 0) in (PLACEHOLDER, OTHER_LANGUAGE)
            color = theme.MUTED if preliminary else theme.TROPHY
        else:
            text, color = "Noch keine Trophäenliste – wird täglich geprüft", theme.MUTED
        self.trophy_status.configure(text=text, text_color=color)
        has_match = bool(exo_id) and exo_id != IGNORE
        self.check_btn.configure(state='normal' if has_achievements(self.game) else 'disabled')
        self.wrong_btn.configure(state='normal' if has_match else 'disabled')
        self.open_btn.configure(state='normal' if has_match and self._trophy_value('exophase_url') else 'disabled')
        self.psnp_btn.configure(state='normal' if has_achievements(self.game) else 'disabled')

    def check_trophies(self):
        self.check_btn.configure(state='disabled')
        self._update_trophy_status(("Suche auf Exophase…", theme.MUTED))
        game = {**self.game, 'exophase_id': '', 'exophase_platform': '', 'exophase_quality': UNRATED}

        def work():
            try:
                entry, platform, quality, language = self.app.trophies.find(game)
                self.app.call(done, entry, platform, quality, language, None)
            except Exception as e:
                self.app.call(done, None, None, UNRATED, '', e)

        def done(entry, platform, quality, language, error):
            if not self.winfo_exists():
                return
            if error:
                self._update_trophy_status(("⚠️ Exophase nicht erreichbar", theme.WARNING))
            elif entry:
                self.trophy_fields = {
                    'exophase_id': str(entry.get('master_id', '')),
                    'exophase_title': entry.get('title', ''),
                    'exophase_url': entry.get('endpoint_awards', ''),
                    'exophase_platform': platform,
                    'exophase_quality': quality,
                    'exophase_language': language,
                    'psn_trophy_count': int(entry.get('total_awards') or 0),
                }
                self._update_trophy_status()
            else:
                self.trophy_fields = {'exophase_id': '', 'exophase_title': '', 'exophase_url': '',
                                      'exophase_platform': '', 'exophase_quality': UNRATED,
                                      'exophase_language': '', 'psn_trophy_count': 0}
                self._update_trophy_status(("Noch keine Trophäenliste gefunden", theme.MUTED))
            self.check_btn.configure(state='normal')

        threading.Thread(target=work, daemon=True).start()

    def ignore_match(self):
        self.trophy_fields = {'exophase_id': IGNORE, 'exophase_title': '', 'exophase_url': '',
                              'exophase_platform': '', 'exophase_quality': UNRATED, 'exophase_language': '',
                              'psn_trophy_count': 0}
        self._update_trophy_status()

    def open_psnprofiles(self):
        webbrowser.open(psnprofiles_url(self.game))

    def open_exophase(self):
        url = self._trophy_value('exophase_url')
        if url:
            webbrowser.open(url)

    def save(self):
        date = self.release_date.get().strip()
        igdb_id = self.igdb_id.get().strip()

        if igdb_id and not igdb_id.isdigit():
            self.error.configure(text="Die IGDB-ID muss eine Zahl sein.")
            return
        if date:
            try:
                datetime.strptime(date, "%d.%m.%Y")
            except ValueError:
                self.error.configure(text="Ungültiges Datum – bitte TT.MM.JJJJ verwenden.")
                return

        manual_tba = self.manual_tba.get()
        last_known = self.game.get('last_known_date', '')
        if manual_tba and date and not last_known:
            last_known = date

        fields = dict(display_name=self.display_name.get().strip(), release_date=date,
                      platforms=self.platforms.get().strip(), igdb_id=igdb_id, hyped=self.hyped.get(),
                      manual_tba=manual_tba, last_known_date=last_known, **self.trophy_fields)
        if date != self.game.get('release_date'):
            fields['release_window'] = ''   # von Hand ein genaues Datum gesetzt → kein „Q2 2027“ mehr
        self.app.store.update_game(self.uid, **fields)
        self.close()

    def toggle_archive(self):
        self.app.store.set_archived(self.uid, not self.game.get('archived'))
        self.close()

    def confirm_delete(self):
        def delete():
            self.app.store.delete_game(self.uid)
            self.close()
        ConfirmDialog(self.app, "Spiel löschen?", f"„{title(self.game)}“ wird aus dem Tracker entfernt.",
                      on_confirm=delete)
