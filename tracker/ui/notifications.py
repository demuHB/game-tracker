"""Benachrichtigungscenter."""
from datetime import datetime

import customtkinter as ctk

from . import theme
from .widgets import ScrollFrame, BaseWindow, ConfirmDialog, empty_state

ICONS = {
    'date_change': '📅',
    'upcoming_release': '⏰',
    'name_change': '✏️',
    'waitlist_match': '🔔',
    'trophy_added': '🏆',
    'update': '⬆️',
}


class NotificationsWindow(BaseWindow):
    def __init__(self, app, on_close=None):
        super().__init__(app, "Benachrichtigungen", 700, 660, on_close=on_close)
        self.header("Benachrichtigungen", "")

        self.buttons = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=0)
        self.buttons.pack(fill='x', side='bottom')
        self.read_btn = ctk.CTkButton(self.buttons, text="✓  Alle als gelesen markieren",
                                      command=self._mark_all_read, **theme.button_style('primary'))
        self.read_btn.pack(side='right', padx=(6, 20), pady=12)
        self.clear_btn = ctk.CTkButton(self.buttons, text="🗑  Alle löschen", command=self._confirm_clear,
                                       **theme.button_style('ghost'))
        self.clear_btn.pack(side='left', padx=20, pady=12)

        self.list = ScrollFrame(self, fg_color='transparent')
        self.list.pack(fill='both', expand=True, padx=14, pady=10)
        self.render()

    def render(self):
        for child in self.list.winfo_children():
            child.destroy()
        notifications = list(self.app.store.notifications)
        unread = self.app.store.unread_count()
        self.subtitle_label.configure(text=f"{unread} ungelesen · {len(notifications)} gesamt")
        self.read_btn.configure(state='normal' if unread else 'disabled')
        self.clear_btn.configure(state='normal' if notifications else 'disabled')

        if not notifications:
            empty_state(self.list, "🔔", "Keine Benachrichtigungen",
                        "Hier erscheinen neue Release-Daten, Erinnerungen,\nWartelisten-Treffer und Trophäen-News.")
            return
        for n in notifications:
            self._card(n)

    def _card(self, n):
        unread = not n.get('read')
        card = ctk.CTkFrame(self.list, fg_color=theme.UNREAD_BG if unread else theme.CARD, corner_radius=theme.RADIUS,
                            border_width=1 if unread else 0, border_color='#2f6f7a')
        card.pack(fill='x', padx=6, pady=4)
        card.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(card, text=ICONS.get(n.get('type'), '📢'), font=(theme.EMOJI_FAMILY, 20), width=36
                     ).grid(row=0, column=0, rowspan=3, padx=(12, 6), pady=10, sticky='n')
        title_text = n.get('title', '')
        # Emoji am Titelanfang doppelt sich mit dem Icon – entfernen
        if title_text[:1] and not title_text[:1].isalnum():
            title_text = title_text[1:].strip()
        ctk.CTkLabel(card, text=title_text, font=theme.BODY_BOLD, text_color=theme.TEXT, anchor='w'
                     ).grid(row=0, column=1, sticky='ew', pady=(10, 0))
        if unread:
            ctk.CTkLabel(card, text="NEU", font=theme.font(9, 'bold'), fg_color=theme.SUCCESS_DARK,
                         text_color='white', corner_radius=5, height=18, padx=6
                         ).grid(row=0, column=2, padx=12, pady=(10, 0), sticky='e')
        ctk.CTkLabel(card, text=n.get('message', ''), font=theme.SMALL, text_color=theme.MUTED, anchor='w',
                     justify='left', wraplength=540).grid(row=1, column=1, columnspan=2, sticky='ew', padx=(0, 12))
        try:
            ts = datetime.fromisoformat(n['timestamp']).strftime('%d.%m.%Y %H:%M')
        except (KeyError, ValueError):
            ts = ''
        ctk.CTkLabel(card, text=ts, font=theme.TINY, text_color=theme.SUBTLE, anchor='w'
                     ).grid(row=2, column=1, sticky='ew', pady=(0, 10))

    def _mark_all_read(self):
        self.app.store.mark_all_read()
        self.close()   # öffnet die Spieleliste wieder, falls das Fenster aus ihr heraus geöffnet wurde

    def _confirm_clear(self):
        ConfirmDialog(self.app, "Alle Benachrichtigungen löschen?", "Das kann nicht rückgängig gemacht werden.",
                      on_confirm=self.app.store.clear_notifications)
