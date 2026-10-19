"""Tray-Flyout: die Spieleliste unten rechts über der Taskleiste.

Wird einmal gebaut und danach nur ein-/ausgeblendet; die Kartenliste wird nur neu
aufgebaut, wenn sich die Spieldaten (oder das Tagesdatum) geändert haben.
"""
import ctypes
import json
import time
import tkinter
import webbrowser
from datetime import date, datetime

import customtkinter as ctk

from .. import config
from ..models import is_tba, sort_key_archive, sort_key_dated, sort_key_tba
from . import theme
from .gamelist import GameList
from .widgets import monitor_at_cursor, sync_scaling

WIDTH, HEIGHT = 480, 620


class Popup(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app.root, fg_color=theme.BORDER)
        self.app = app
        self.page = 0
        self.withdraw()
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        self._position()

        # 1px-Rahmen über den äußeren Hintergrund
        self.shell = ctk.CTkFrame(self, fg_color=theme.BG, corner_radius=0)
        self.shell.pack(fill='both', expand=True, padx=1, pady=1)

        self._build_header()
        self._build_tabs()
        self._build_footer()
        self.list = GameList(self.shell, app, on_open=self._open_game, on_link=self._open_link,
                             on_archive=self._archive)
        self.list.pack(fill='both', expand=True)
        self._data = ([], [], [])
        self._signature = None
        self.closed_at = 0.0
        self.render()

        self.bind('<Escape>', lambda e: self.close())
        self.bind('<FocusOut>', lambda e: self.after(200, self._check_focus))
        self.bind('<FocusIn>', lambda e: setattr(self, '_had_focus', True))
        self._had_focus = False

    def _position(self):
        """Unten rechts, direkt über der Taskleiste.

        CTk skaliert bei geometry() auch die Position mit der Windows-Anzeigeskalierung –
        daher nur die Größe über CTk setzen und mit der unskalierten Tk-Methode in echten Pixeln platzieren.
        """
        (left, top, right, bottom), scale = monitor_at_cursor(self)
        tkinter.Wm.wm_geometry(self, f"+{left + 20}+{top + 20}")   # erst auf den Monitor des Klicks …
        sync_scaling(self, scale)                                 # … dann dessen Skalierung übernehmen
        margin = int(10 * scale)
        height = min(HEIGHT, int((bottom - top - 2 * margin) / scale))
        self.geometry(f"{WIDTH}x{height}")
        x = right - int(WIDTH * scale) - margin
        y = bottom - int(height * scale) - margin
        tkinter.Wm.wm_geometry(self, f"+{x}+{y}")

    @property
    def is_open(self):
        return self.winfo_exists() and self.state() == 'normal'

    def show(self):
        self._position()
        if self.page != 0:
            self.page = 0              # immer mit „Mit Datum“ öffnen
            self._signature = None     # Liste der ersten Seite neu zeichnen
        self.render()
        self.list.ensure_scale()   # nach Monitorwechsel mit neuer Skalierung neu zeichnen
        self._had_focus = False
        self.deiconify()
        self.after(30, self._grab_focus)
        self._mouse_was_down = True   # Klick, der das Fenster geöffnet hat, nicht mitzählen
        self.after(50, self._watch_clicks)

    def _watch_clicks(self):
        """Schließt das Flyout bei jedem Mausklick außerhalb.

        Randlose Tray-Fenster bekommen unter Windows oft keinen Fokus – auf FocusOut allein
        ist daher kein Verlass. Solange es offen ist, wird der Maustastenzustand abgefragt.
        """
        if not self.is_open:
            return
        try:
            state = ctypes.windll.user32.GetAsyncKeyState
            down = bool(state(0x01) & 0x8000 or state(0x02) & 0x8000)  # linke/rechte Maustaste
        except (AttributeError, OSError):
            return
        if down and not self._mouse_was_down:
            x, y = self.winfo_pointerxy()
            inside = (self.winfo_rootx() <= x < self.winfo_rootx() + self.winfo_width()
                      and self.winfo_rooty() <= y < self.winfo_rooty() + self.winfo_height())
            if not inside:
                self.close()
                return
        self._mouse_was_down = down
        self.after(50, self._watch_clicks)

    # ------------------------------------------------------------- Aufbau
    def _build_header(self):
        head = ctk.CTkFrame(self.shell, fg_color=theme.SURFACE, corner_radius=0)
        head.pack(fill='x')
        left = ctk.CTkFrame(head, fg_color='transparent')
        left.pack(side='left', padx=16, pady=12)
        ctk.CTkLabel(left, text="Meine Hype Games", font=theme.H1, text_color=theme.TEXT).pack(anchor='w')
        self.subtitle = ctk.CTkLabel(left, text="", font=theme.SMALL, text_color=theme.MUTED, height=16)
        self.subtitle.pack(anchor='w')

        btns = ctk.CTkFrame(head, fg_color='transparent')
        btns.pack(side='right', padx=12)

        def icon_btn(text, command, kind='subtle', tip=None):
            b = ctk.CTkButton(btns, text=text, command=command, width=36, height=36, corner_radius=9,
                              font=(theme.EMOJI_FAMILY, 15), **{k: v for k, v in theme.button_style(kind).items()
                                                                 if k in ('fg_color', 'hover_color', 'text_color')})
            b.pack(side='left', padx=3)
            return b

        self.add_btn = icon_btn("＋", lambda: self.app.open_add_dialog(from_popup=True), 'success')
        self.refresh_btn = icon_btn("⟳", self._refresh)
        bell_wrap = ctk.CTkFrame(btns, fg_color='transparent')
        bell_wrap.pack(side='left')
        self.bell_btn = ctk.CTkButton(bell_wrap, text="🔔", width=36, height=36, corner_radius=9,
                                      font=(theme.EMOJI_FAMILY, 14), fg_color=theme.CARD, hover_color=theme.CARD_HOVER,
                                      command=lambda: self.app.open_notifications(from_popup=True))
        self.bell_btn.pack(padx=3)
        # Badge liegt IN der Glocke: seine abgerundeten Ecken nehmen so die Glockenfarbe an
        # (vorher die Farbe der Kopfleiste → dunkles Quadrat hinter dem roten Punkt)
        self.badge = ctk.CTkLabel(self.bell_btn, text="", font=theme.font(9, 'bold'), fg_color=theme.DANGER,
                                  text_color='white', corner_radius=8, width=18, height=16)
        self.badge.bind('<Button-1>', lambda e: self.app.open_notifications(from_popup=True))
        self.bell_btn.bind('<Enter>', lambda e: self._sync_badge(hover=True), add='+')
        self.bell_btn.bind('<Leave>', lambda e: self._sync_badge(hover=False), add='+')
        close = ctk.CTkButton(btns, text="✕", width=30, height=30, corner_radius=8, font=theme.BODY_BOLD,
                              fg_color='transparent', hover_color=theme.DANGER_DARK, text_color=theme.MUTED,
                              command=self.close)
        close.pack(side='left', padx=(6, 0))

    def _sync_badge(self, hover):
        color = self.bell_btn.cget('hover_color' if hover else 'fg_color')
        self.badge.configure(bg_color=color)

    def _build_tabs(self):
        bar = ctk.CTkFrame(self.shell, fg_color=theme.SURFACE, corner_radius=0)
        bar.pack(fill='x')
        self.tabs = ctk.CTkSegmentedButton(bar, values=["a", "b"], command=self._on_tab, height=32,
                                           font=theme.SMALL_BOLD, corner_radius=8,
                                           fg_color=theme.BG, unselected_color=theme.BG,
                                           unselected_hover_color=theme.CARD, selected_color=theme.ACCENT,
                                           selected_hover_color=theme.ACCENT_HOVER, text_color=theme.TEXT)
        self.tabs.pack(fill='x', padx=14, pady=(0, 10))

    def _build_footer(self):
        foot = ctk.CTkFrame(self.shell, fg_color=theme.SURFACE, corner_radius=0, height=34)
        foot.pack(fill='x', side='bottom')
        self.footer_label = ctk.CTkLabel(foot, text="", font=theme.TINY, text_color=theme.MUTED)
        self.footer_label.pack(side='left', padx=14, pady=6)
        # Unauffälliger Schalter für die Jahres-Ansicht (Zustand in config.json)
        self.by_year = ctk.BooleanVar(value=bool(self.app.store.config.get('view_by_year')))
        ctk.CTkSwitch(foot, text="Jahre", variable=self.by_year, command=self._toggle_years, font=theme.TINY,
                      text_color=theme.MUTED, switch_width=26, switch_height=13, progress_color=theme.ACCENT,
                      button_color=theme.MUTED, button_hover_color=theme.TEXT, fg_color=theme.BORDER, width=60
                      ).pack(side='right', padx=(4, 12))
        self.waitlist_link = ctk.CTkLabel(foot, text="", font=theme.font(10, 'bold'), text_color=theme.ACCENT,
                                          cursor='hand2')
        self.waitlist_link.bind('<Button-1>', lambda e: self.app.open_waitlist(from_popup=True))

    # ------------------------------------------------------------- Inhalt
    def render(self):
        store = self.app.store
        games = store.snapshot()
        active = [g for g in games if not g.get('archived')]
        dated = sorted((g for g in active if not is_tba(g)), key=sort_key_dated)
        tba = sorted((g for g in active if is_tba(g)), key=sort_key_tba)
        archive = sorted((g for g in games if g.get('archived')), key=sort_key_archive, reverse=True)

        subtitle = f"{len(active)} Spiele · {sum(1 for g in active if g.get('hyped'))} gehypt"
        if archive:
            subtitle += f" · {len(archive)} im Archiv"
        self.subtitle.configure(text=subtitle)
        labels = [f"Mit Datum ({len(dated)})", f"Ohne Datum ({len(tba)})", f"Archiv ({len(archive)})"]
        self.tabs.configure(values=labels)
        self.tabs.set(labels[self.page])

        unread = store.unread_count()
        if unread:
            self.badge.configure(text=str(unread))
            self.badge.place(relx=1.0, x=-1, y=1, anchor='ne')
            self.bell_btn.configure(fg_color=theme.WARNING, hover_color='#d68c22')
            self._sync_badge(hover=False)
        else:
            self.badge.place_forget()
            self.bell_btn.configure(fg_color=theme.CARD, hover_color=theme.CARD_HOVER)

        last = store.config.get('last_update', '')
        try:
            text = f"Aktualisiert {datetime.fromisoformat(last).strftime('%d.%m. %H:%M')}"
        except ValueError:
            text = "Klick auf ein Spiel zum Bearbeiten"
        if self.app.updater.running:
            text = "Aktualisiere…"
        elif self.app.updater.last_error:
            text = "⚠️ Update fehlgeschlagen – offline?"
        self.footer_label.configure(text=f"v{config.APP_VERSION}  ·  {text}")
        if store.waitlist:
            self.waitlist_link.configure(text=f"📋 {len(store.waitlist)} auf Warteliste")
            self.waitlist_link.pack(side='right', padx=14)
        else:
            self.waitlist_link.pack_forget()
        self.refresh_btn.configure(state='disabled' if self.app.updater.running else 'normal')

        # Kartenliste nur bei echten Datenänderungen neu bauen
        signature = json.dumps(games, sort_keys=True) + date.today().isoformat() + str(self.by_year.get())
        if signature != self._signature:
            self._signature = signature
            self._data = (dated, tba, archive)
            self._show_page()

    def _show_page(self):
        games = self._data[self.page]
        empty = ("Keine Spiele mit Datum", "Keine Spiele ohne Datum", "Archiv ist leer")[self.page]
        self.list.set_games(games, with_gaps=self.page != 1, empty_text=empty, by_year=self.by_year.get())

    def _on_tab(self, value):
        new_page = next((i for i, prefix in enumerate(("Mit Datum", "Ohne Datum", "Archiv"))
                         if value.startswith(prefix)), 0)
        if new_page != self.page:
            self.page = new_page
            self._show_page()

    def _toggle_years(self):
        self.app.store.config['view_by_year'] = bool(self.by_year.get())
        self.app.store.save_config()
        self._signature = None
        self.render()

    def _archive(self, uid):
        self.app.store.set_archived(uid, True)

    # ------------------------------------------------------------- Aktionen
    def _open_game(self, uid):
        self.app.open_edit_dialog(uid, from_popup=True)

    def _open_link(self, url):
        webbrowser.open(url)
        self.close()

    def _refresh(self):
        self.refresh_btn.configure(state='disabled')
        self.footer_label.configure(text="Aktualisiere…")
        self.app.start_update()

    def _grab_focus(self):
        if self.winfo_exists():
            self.lift()
            self.focus_force()

    def _check_focus(self):
        """Schließt das Flyout, sobald der Fokus woanders hingeht (Klick außerhalb).

        Nur wenn es vorher wirklich den Fokus hatte – Windows verweigert Hintergrundprozessen
        manchmal den Vordergrund, dann bleibt es offen bis ✕/Esc/Tray-Klick.
        """
        if not self.is_open or not self._had_focus:
            return
        try:
            focused = self.focus_get()
        except (KeyError, AttributeError):
            focused = None
        if focused is None or focused.winfo_toplevel() is not self:
            x, y = self.winfo_pointerxy()
            under = self.winfo_containing(x, y)
            if under is None or under.winfo_toplevel() is not self:
                self.close()

    def close(self):
        if self.is_open:
            self.closed_at = time.monotonic()
            self.withdraw()
