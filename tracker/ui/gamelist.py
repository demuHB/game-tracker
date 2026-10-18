"""Spieleliste als EINE gezeichnete Fläche (tk.Canvas) statt vieler CTk-Widgets.

Jede Karte aus ~8 CTk-Widgets (je mit eigener Canvas) baute sich sichtbar auf und
hinterließ beim schnellen Scrollen Artefakte. Hier werden alle Karten selbst gezeichnet:
Hintergründe, Pills und Chips als geglättete PIL-Bilder, Texte und Linien als Canvas-Elemente.
Neu zeichnen dauert nur Millisekunden; Scrollen verschiebt nur noch eine Fläche.
"""
import tkinter
import tkinter.font as tkfont

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk

from collections import Counter

from ..models import days_between, days_until, is_tba, platform_list, release_year, short_platform, title
from . import theme
from ..trophies import trophy_link
from .widgets import SmoothWheel, countdown_info

COVER = (46, 62)          # logische Pixel
PAD = 10                  # Innenabstand der Karte
GAP = 8                   # Abstand zwischen Karten
SEPARATOR = 18            # Höhe der Tagesabstand-Zeile
TROPHY_BG = '#1b2f4d'
TROPHY_BG_HOVER = '#27446e'
ARCHIVE_BG = '#2a3048'
ARCHIVE_BG_HOVER = '#3a4262'
YEAR_HEADER = 30           # Höhe der Jahres-Überschrift


def _rgb(color):
    color = color.lstrip('#')
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


class GameList(SmoothWheel, tkinter.Frame):
    """Liste der Spielkarten. on_open(uid) beim Klick auf eine Karte, on_link(url) beim 🏆-Abzeichen."""

    def __init__(self, master, app, on_open, on_link, on_archive=None):
        super().__init__(master, bg=theme.BG, bd=0, highlightthickness=0)
        self.app = app
        self.on_open = on_open
        self.on_link = on_link
        self.on_archive = on_archive
        self.canvas = tkinter.Canvas(self, bg=theme.BG, highlightthickness=0, bd=0)
        self.scrollbar = ctk.CTkScrollbar(self, command=self.canvas.yview, button_color=theme.BORDER,
                                          button_hover_color=theme.SUBTLE, fg_color='transparent', width=12)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side='right', fill='y', padx=(0, 2))
        self.canvas.pack(side='left', fill='both', expand=True)
        self._register_wheel(self.canvas)

        self._games, self._with_gaps, self._empty, self._by_year = [], False, '', False
        self._canvas_width = 0
        self._shapes = {}       # Cache: (w, h, r, fill, border) → PhotoImage
        self._cards = {}        # uid → (bg-Item-ID, normal-Bild, hover-Bild)
        self._links = {}        # Canvas-Tag → Abzeichen (Aktion, Bild-Item, Breite, Farben)
        self._hover = None
        self._fonts = {}
        self._drawn_scale = None

        self.canvas.bind('<Configure>', self._on_resize)
        self.canvas.bind('<Motion>', self._on_motion)
        self.canvas.bind('<Leave>', lambda e: self._set_hover(None))
        self.canvas.bind('<Button-1>', self._on_click)

    # ------------------------------------------------------------- öffentlich
    def set_games(self, games, with_gaps, empty_text, by_year=False):
        """by_year: Jahres-Überschriften („2027 ── 8 Spiele“) statt Tagesabstand an Jahresgrenzen."""
        self._games, self._with_gaps, self._empty, self._by_year = list(games), with_gaps, empty_text, by_year
        self._redraw()
        self.canvas.yview_moveto(0)

    # ------------------------------------------------------------- Hilfen
    @property
    def scale(self):
        return ctk.ScalingTracker.get_widget_scaling(self)

    def px(self, value):
        return int(round(value * self.scale))

    def font(self, size, weight='normal'):
        key = (size, weight, self.scale)   # Skalierung gehört dazu – sonst bleibt die Schrift nach Monitorwechsel klein
        if key not in self._fonts:
            self._fonts[key] = tkfont.Font(family=theme.FONT_FAMILY, size=-self.px(size), weight=weight)
        return self._fonts[key]

    def shape(self, w, h, radius, fill, border=None, border_width=0):
        """Abgerundetes Rechteck als geglättetes Bild (Tk-Canvas kann kein Antialiasing)."""
        key = (w, h, radius, fill, border, border_width)
        if key not in self._shapes:
            k = 3  # in dreifacher Größe zeichnen, dann verkleinern → glatte Kanten
            img = Image.new('RGBA', (w * k, h * k), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            box = (0, 0, w * k - 1, h * k - 1)
            if border and border_width:
                draw.rounded_rectangle(box, radius * k, fill=_rgb(border))
                inset = border_width * k
                draw.rounded_rectangle((inset, inset, w * k - 1 - inset, h * k - 1 - inset),
                                       max(0, radius - border_width) * k, fill=_rgb(fill))
            else:
                draw.rounded_rectangle(box, radius * k, fill=_rgb(fill))
            self._shapes[key] = ImageTk.PhotoImage(img.resize((w, h), Image.LANCZOS))
        return self._shapes[key]

    def pill(self, x, y, text, colors, font, tags, pad_x=8, height=22, radius=6, outline=None):
        """Zeichnet eine Pill ab (x, y) links oben; gibt ihre Breite zurück. outline = Farbe der Kontur."""
        bg, fg = colors
        w = font.measure(text) + self.px(pad_x) * 2
        h = self.px(height)
        image = (self.shape(w, h, self.px(radius), bg, outline, max(2, self.px(2))) if outline
                 else self.shape(w, h, self.px(radius), bg))
        self.canvas.create_image(x, y, image=image, anchor='nw', tags=tags)
        self.canvas.create_text(x + w // 2, y + h // 2, text=text, fill=fg, font=font, tags=tags)
        return w

    # ------------------------------------------------------------- Zeichnen
    def _on_resize(self, event):
        if abs(event.width - self._canvas_width) > 2 or self.scale != self._drawn_scale:
            self._redraw()

    def ensure_scale(self):
        """Neu zeichnen, falls sich die Skalierung seit dem letzten Zeichnen geändert hat (Monitorwechsel)."""
        if self.scale != self._drawn_scale:
            self._redraw()

    def _redraw(self):
        c = self.canvas
        c.delete('all')
        self._cards.clear()
        self._links.clear()
        self._hover = None
        self._canvas_width = c.winfo_width()
        self._drawn_scale = self.scale
        if self._canvas_width < 50:  # noch nicht angezeigt → beim ersten <Configure> zeichnen
            return
        if not self._games:
            self._draw_empty()
            return

        x0, x1 = self.px(10), self._canvas_width - self.px(4)
        y = self.px(6)
        years = [release_year(g) for g in self._games] if self._by_year else []
        per_year = Counter(years)
        for i, game in enumerate(self._games):
            new_year = self._by_year and (i == 0 or years[i] != years[i - 1])
            if new_year:
                y = self._draw_year(y, years[i], per_year[years[i]])
            elif self._with_gaps and i > 0:
                gap = days_between(self._games[i - 1], game)
                if gap:
                    y = self._draw_separator(y, gap)
            y = self._draw_card(game, x0, x1, y) + self.px(GAP)
        c.configure(scrollregion=(0, 0, self._canvas_width, y + self.px(4)))

    def _draw_empty(self):
        c, mid = self.canvas, self._canvas_width // 2
        c.create_text(mid, self.px(110), text="⏳", font=(theme.EMOJI_FAMILY, -self.px(40)), fill=theme.MUTED)
        c.create_text(mid, self.px(160), text=self._empty, font=self.font(14, 'bold'), fill=theme.MUTED)
        c.create_text(mid, self.px(186), text="Klicke auf ＋ um Spiele hinzuzufügen", font=self.font(11),
                      fill=theme.SUBTLE)
        c.configure(scrollregion=(0, 0, self._canvas_width, self.px(220)))

    def _draw_year(self, y, year, count):
        """Schlichte Jahres-Überschrift: „2027 ───────── 8 Spiele“."""
        c = self.canvas
        top = y + (self.px(8) if y > self.px(6) else 0)
        mid_y = top + self.px(YEAR_HEADER) // 2
        left = self.px(14)
        label = str(year) if year else "Ohne Jahr"
        title_font, count_font = self.font(13, 'bold'), self.font(10)
        count_text = f"{count} {'Spiel' if count == 1 else 'Spiele'}"
        c.create_text(left, mid_y, text=label, anchor='w', font=title_font, fill=theme.TEXT)
        right = self._canvas_width - self.px(14)
        c.create_text(right, mid_y, text=count_text, anchor='e', font=count_font, fill=theme.SUBTLE)
        c.create_line(left + title_font.measure(label) + self.px(10), mid_y,
                      right - count_font.measure(count_text) - self.px(10), mid_y, fill=theme.BORDER)
        return top + self.px(YEAR_HEADER)

    def _badge(self, x, top, text, tags, colors, action, link_tag):
        """Klickbares Abzeichen (🏆 / Archivieren) rechtsbündig bis x; gibt die neue linke Kante zurück."""
        c = self.canvas
        bg, bg_hover, fg = colors
        font = self.font(10, 'bold')
        w = font.measure(text) + self.px(16)
        x -= w
        item = c.create_image(x, top + self.px(1), anchor='nw', tags=tags,
                              image=self.shape(w, self.px(20), self.px(6), bg))
        c.create_text(x + w // 2, top + self.px(11), text=text, font=font, fill=fg, tags=tags)
        if action:
            self._links[link_tag] = (action, item, w, bg, bg_hover)
        return x - self.px(4)

    def _draw_separator(self, y, days):
        c = self.canvas
        mid_y = y + self.px(SEPARATOR) // 2
        text = f"{days} {'Tag' if days == 1 else 'Tage'}"
        font = self.font(10)
        half = font.measure(text) // 2 + self.px(8)
        mid_x = self._canvas_width // 2
        c.create_line(self.px(18), mid_y, mid_x - half, mid_y, fill=theme.BORDER)
        c.create_line(mid_x + half, mid_y, self._canvas_width - self.px(18), mid_y, fill=theme.BORDER)
        c.create_text(mid_x, mid_y, text=text, font=font, fill=theme.SUBTLE)
        return y + self.px(SEPARATOR)

    def _draw_card(self, game, x0, x1, y):
        """Zeichnet eine Karte ab y; gibt die Unterkante zurück."""
        c = self.canvas
        uid = game['uid']
        tag = f'card:{uid}'
        hyped = bool(game.get('hyped'))
        pad = self.px(PAD)
        cover_w, cover_h = self.px(COVER[0]), self.px(COVER[1])
        text_x = x0 + pad + cover_w + pad
        right = x1 - pad

        # Platzhalter für den Hintergrund – wird nach der Höhenberechnung gesetzt
        bg_item = c.create_image(x0, y, anchor='nw', tags=(tag,))

        # Cover (nachgeladene Cover werden ersetzt)
        name = title(game)
        cover_item = c.create_image(x0 + pad, y + pad, anchor='nw', tags=(tag,))

        def set_cover(item=cover_item):
            if c.winfo_exists() and c.type(item):
                c.itemconfigure(item, image=self.app.covers.get_tk(game.get('cover_id'), (cover_w, cover_h), name))
        c.itemconfigure(cover_item, image=self.app.covers.get_tk(game.get('cover_id'), (cover_w, cover_h), name,
                                                                 on_ready=set_cover))

        # Zeile 1: Badges rechts, Name links (mit Umbruch)
        top = y + self.px(9)
        badge_font = self.font(10, 'bold')
        badge_x = right
        if game.get('manual_tba'):
            w = badge_font.measure("TBA") + self.px(14)
            badge_x -= w
            self.pill(badge_x, top + self.px(1), "TBA", (theme.BORDER, theme.MUTED), badge_font, (tag,),
                      pad_x=7, height=20)
            badge_x -= self.px(4)
        if game.get('psn_trophy_count') or game.get('psnprofiles_link'):
            url = trophy_link(game)   # hinterlegter PSNProfiles-Link, sonst die Exophase-Liste
            link_tag = f'link:{uid}'
            count = game.get('psn_trophy_count')
            badge_x = self._badge(badge_x, top, f"🏆 {count}" if count else "🏆",
                                  (tag, link_tag) if url else (tag,),
                                  # vorläufige Liste (Platzhalter/andere Sprache): blasser
                                  (TROPHY_BG, TROPHY_BG_HOVER,
                                   theme.SUBTLE if game.get('exophase_quality') in (0, 1) else theme.TROPHY),
                                  (lambda u=url: self.on_link(u)) if url else None, link_tag)
        days = days_until(game.get('release_date'))
        if (self.on_archive and not game.get('archived') and not is_tba(game)
                and days is not None and days < 0):
            # Vorschlag: erschienenes Spiel mit einem Klick ins Archiv
            archive_tag = f'archive:{uid}'
            badge_x = self._badge(badge_x, top, "🗄 Archivieren", (tag, archive_tag),
                                  (ARCHIVE_BG, ARCHIVE_BG_HOVER, theme.MUTED),
                                  lambda u=uid: self.on_archive(u), archive_tag)

        name_item = c.create_text(text_x, top, anchor='nw', text=('★ ' if hyped else '') + name,
                                  font=self.font(13, 'bold'), fill=theme.GOLD if hyped else theme.TEXT,
                                  width=max(self.px(80), badge_x - text_x - self.px(6)), tags=(tag,))
        line_y = c.bbox(name_item)[3] + self.px(4)

        # Zeile 2: Plattform-Chips
        platforms = platform_list(game.get('platforms'))
        if platforms:
            chip_font = self.font(10)
            cx = text_x
            for p in platforms:
                is_ps = 'playstation' in p.lower()
                colors = ('#1d3557', '#9cc7ff') if is_ps else (theme.BORDER, theme.MUTED)
                label = short_platform(p)
                if cx + chip_font.measure(label) + self.px(12) > right:
                    break  # passt nicht mehr in die Zeile
                cx += self.pill(cx, line_y, label, colors, chip_font, (tag,), pad_x=6, height=18, radius=5)
                cx += self.px(4)
            line_y += self.px(18) + self.px(5)
        else:
            line_y += self.px(2)

        # Zeile 3: Countdown
        text, colors, outline = countdown_info(game)
        self.pill(text_x, line_y, text, colors, self.font(11, 'bold'), (tag,), outline=outline)
        content_bottom = line_y + self.px(22) + pad

        bottom = max(y + pad + cover_h + pad, content_bottom)
        height = bottom - y
        width = x1 - x0
        radius = self.px(theme.RADIUS)
        if hyped:
            border = self.px(2)
            normal = self.shape(width, height, radius, theme.HYPE_BG, theme.HYPE_BORDER, border)
            hover = self.shape(width, height, radius, theme.HYPE_HOVER, theme.HYPE_BORDER, border)
        else:
            normal = self.shape(width, height, radius, theme.CARD)
            hover = self.shape(width, height, radius, theme.CARD_HOVER)
        c.itemconfigure(bg_item, image=normal)
        self._cards[uid] = (bg_item, normal, hover)
        return bottom

    # ------------------------------------------------------------- Interaktion
    def _tags_at(self, event):
        c = self.canvas
        x, y = c.canvasx(event.x), c.canvasy(event.y)
        items = c.find_overlapping(x, y, x, y)
        tags = set()
        for item in items:
            tags.update(c.gettags(item))
        return tags

    def _on_motion(self, event):
        tags = self._tags_at(event)
        uid = next((t[5:] for t in tags if t.startswith('card:')), None)
        link = next((t for t in tags if t in self._links), None)
        self._set_hover(uid, link)

    def _set_hover(self, uid, link=None):
        hover_key = (uid, link)
        if hover_key == self._hover:
            return
        c = self.canvas
        old_uid, old_link = self._hover or (None, None)
        if old_uid in self._cards:
            item, normal, _ = self._cards[old_uid]
            c.itemconfigure(item, image=normal)
        if old_link in self._links:
            _, item, w, bg, _ = self._links[old_link]
            c.itemconfigure(item, image=self.shape(w, self.px(20), self.px(6), bg))
        if uid in self._cards:
            item, _, hover = self._cards[uid]
            c.itemconfigure(item, image=hover)
        if link in self._links:
            _, item, w, _, bg_hover = self._links[link]
            c.itemconfigure(item, image=self.shape(w, self.px(20), self.px(6), bg_hover))
        c.configure(cursor='hand2' if uid else '')
        self._hover = hover_key

    def _on_click(self, event):
        tags = self._tags_at(event)
        link = next((t for t in tags if t in self._links), None)
        if link:
            self._links[link][0]()   # Abzeichen-Aktion (Exophase öffnen / archivieren) statt Bearbeiten
            return
        uid = next((t[5:] for t in tags if t.startswith('card:')), None)
        if uid:
            self.on_open(uid)
