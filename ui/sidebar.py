"""Barra lateral esquerda com as seções do aplicativo."""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from ui import theme
from ui.theme import ICONS

# (chave, nome exibido, ícone) — a ordem define também os atalhos Ctrl+1 … Ctrl+8.
SECTIONS: list[tuple[str, str, str]] = [
    ("home", "Início", "home"),
    ("converter", "Conversor de vídeo", "converter"),
    ("compressor", "Compressor", "compressor"),
    ("audio_extractor", "Extrator de áudio", "audio_extractor"),
    ("frames", "Extrator de frames", "frames"),
    ("analyzer", "Analisador de mídia", "analyzer"),
    ("cutter", "Cortador de vídeo", "cutter"),
    ("audio_converter", "Conversor de áudio", "audio_converter"),
]
SETTINGS_SECTION = ("settings", "Configurações", "settings")
SECTION_TITLES = {key: name for key, name, _ in SECTIONS + [SETTINGS_SECTION]}
SECTION_SUBTITLES = {
    "home": "Central de ferramentas para converter, comprimir, cortar e analisar vídeos e áudios.",
    "converter": "Converta vídeos entre MP4, MKV, AVI, MOV e WebM.",
    "compressor": "Reduza o tamanho dos vídeos mantendo a melhor qualidade possível.",
    "audio_extractor": "Extraia a trilha de áudio de um vídeo em MP3, WAV, AAC, FLAC ou OPUS.",
    "frames": "Salve imagens de instantes específicos do vídeo ou em intervalos regulares.",
    "analyzer": "Veja todos os detalhes técnicos de um arquivo de vídeo ou áudio.",
    "cutter": "Exporte apenas o trecho que você quer, de forma rápida ou precisa.",
    "audio_converter": "Converta arquivos de áudio entre MP3, WAV, FLAC, AAC e OPUS.",
    "settings": "Pastas, desempenho, notificações, FFmpeg e atalhos de teclado.",
}


class _Item(tk.Frame):
    """Um item da sidebar: barra de destaque + ícone + nome."""

    def __init__(self, parent, key: str, text: str, icon: str, on_click: Callable[[str], None]):
        super().__init__(parent, bg=theme.SIDEBAR, cursor="hand2")
        f = theme.fonts(parent)
        self.key = key
        self.selected = False
        self.bar = tk.Frame(self, bg=theme.SIDEBAR, width=3)
        self.bar.pack(side="left", fill="y")
        self.icon = tk.Label(self, text=ICONS[icon], bg=theme.SIDEBAR, fg=theme.TEXT_DIM, font=f["icon_small"],
                             width=3)
        self.icon.pack(side="left", pady=9)
        self.label = tk.Label(self, text=text, bg=theme.SIDEBAR, fg=theme.TEXT_DIM, font=f["base"], anchor="w")
        self.label.pack(side="left", fill="x", expand=True)
        for w in (self, self.icon, self.label):
            w.bind("<Button-1>", lambda e: on_click(key))
            w.bind("<Enter>", lambda e: self._paint(hover=True))
            w.bind("<Leave>", lambda e: self._paint(hover=False))

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self._paint(False)

    def _paint(self, hover: bool) -> None:
        if self.selected:
            bg, fg, bar = theme.SELECTED, theme.TEXT, theme.ACCENT
        elif hover:
            bg, fg, bar = theme.HOVER, theme.TEXT, theme.HOVER
        else:
            bg, fg, bar = theme.SIDEBAR, theme.TEXT_DIM, theme.SIDEBAR
        for w in (self, self.icon, self.label):
            w.configure(bg=bg)
        self.icon.configure(fg=theme.ACCENT if self.selected else fg)
        self.label.configure(fg=fg)
        self.bar.configure(bg=bar)


class Sidebar(tk.Frame):
    def __init__(self, parent, on_select: Callable[[str], None]):
        super().__init__(parent, bg=theme.SIDEBAR, width=230, highlightbackground=theme.BORDER,
                         highlightthickness=0)
        self.pack_propagate(False)
        f = theme.fonts(parent)
        self._items: dict[str, _Item] = {}

        # Marca do aplicativo
        brand = tk.Frame(self, bg=theme.SIDEBAR)
        brand.pack(fill="x", padx=16, pady=(18, 16))
        tk.Label(brand, text=ICONS["play"], bg=theme.ACCENT_DARK, fg="#ffffff", font=f["icon_small"], width=3,
                 pady=4).pack(side="left")
        names = tk.Frame(brand, bg=theme.SIDEBAR)
        names.pack(side="left", padx=10)
        tk.Label(names, text="Mini Video Studio", bg=theme.SIDEBAR, fg=theme.TEXT, font=f["bold"],
                 anchor="w").pack(anchor="w")
        tk.Label(names, text="Ferramentas de mídia", bg=theme.SIDEBAR, fg=theme.TEXT_FAINT, font=f["small"],
                 anchor="w").pack(anchor="w")

        tk.Frame(self, bg=theme.BORDER, height=1).pack(fill="x", padx=14, pady=(0, 8))
        for key, text, icon in SECTIONS:
            self._add(key, text, icon, on_select, side="top")

        # Configurações ficam coladas na base
        self._add(*SETTINGS_SECTION, on_select, side="bottom")
        tk.Frame(self, bg=theme.BORDER, height=1).pack(side="bottom", fill="x", padx=14, pady=(0, 4))

    def _add(self, key: str, text: str, icon: str, on_select, side: str) -> None:
        item = _Item(self, key, text, icon, on_select)
        item.pack(fill="x", side=side, pady=1 if side == "top" else (0, 10))
        self._items[key] = item

    def select(self, key: str) -> None:
        for k, item in self._items.items():
            item.set_selected(k == key)
