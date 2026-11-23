"""Identidade visual do Mini Video Studio: cores, fontes, ícones e estilos ttk.

Paleta inspirada em editores profissionais: camadas de cinza-escuro, valores e
destaques em azul. Tudo que for cor ou fonte deve vir daqui.
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# ---------------------------------------------------------------- cores
BG = "#161616"            # fundo da janela / barra de status
SIDEBAR = "#1b1b1b"       # barra lateral
PANEL = "#202020"         # painéis e cartões
PANEL_ALT = "#262626"     # cabeçalhos, linhas alternadas
FIELD = "#2d2d2d"         # campos de entrada
BORDER = "#333333"        # bordas discretas
BORDER_STRONG = "#444444"
HOVER = "#2a2a2a"
SELECTED = "#26334d"      # item selecionado na sidebar

TEXT = "#e6e6e6"
TEXT_DIM = "#9a9a9a"      # rótulos
TEXT_FAINT = "#6b6b6b"

ACCENT = "#4d8dff"        # azul de destaque (valores, seleção, progresso)
ACCENT_HOVER = "#6aa0ff"
ACCENT_DARK = "#2f5fc4"
SUCCESS = "#4cc38a"
WARNING = "#e5a63b"
DANGER = "#e5534b"
DANGER_HOVER = "#f06a62"

# Paletas de destaque. A escolhida é aplicada na inicialização (ver ``set_theme``).
PALETTES = {
    "dark": {"ACCENT": "#4d8dff", "ACCENT_HOVER": "#6aa0ff", "ACCENT_DARK": "#2f5fc4", "SELECTED": "#26334d"},
    "dark-purple": {"ACCENT": "#a07bff", "ACCENT_HOVER": "#b394ff", "ACCENT_DARK": "#6b46d6",
                    "SELECTED": "#2d2650"},
}
CURRENT_THEME = "dark"          # paleta realmente em uso nesta execução
THEME_LABELS = {"dark": "Escuro · destaque azul", "dark-purple": "Escuro · destaque roxo"}

STATE_COLORS = {
    "waiting": TEXT_DIM,
    "running": ACCENT,
    "done": SUCCESS,
    "cancelled": WARNING,
    "error": DANGER,
}

def set_theme(name: str) -> str:
    """Troca a cor de destaque. Deve ser chamado ANTES de criar a janela e de importar ``ui.widgets``."""
    if name not in PALETTES:
        name = "dark"
    globals().update(PALETTES[name])
    globals()["CURRENT_THEME"] = name
    STATE_COLORS["running"] = globals()["ACCENT"]
    return name


# ---------------------------------------------------------------- ícones (glifos Unicode da fonte Segoe UI Symbol)
ICONS = {
    "home": "⌂",
    "converter": "⇄",
    "compressor": "⇊",
    "audio_extractor": "♪",
    "frames": "▣",
    "analyzer": "◎",
    "cutter": "✂",
    "audio_converter": "♫",
    "settings": "⚙",
    "folder": "▸",
    "open": "↑",
    "cancel": "✕",
    "ok": "✓",
    "info": "ⓘ",
    "help": "?",
    "play": "▶",
    "remove": "✕",
}

# ---------------------------------------------------------------- fontes
_FONT_FAMILY: str | None = None


def font_family(root: tk.Misc | None = None) -> str:
    """Escolhe a melhor fonte disponível: Segoe UI (Windows 10/11) com alternativas."""
    global _FONT_FAMILY
    if _FONT_FAMILY:
        return _FONT_FAMILY
    available = set(tkfont.families(root))
    for name in ("Segoe UI", "Inter", "Helvetica Neue", "DejaVu Sans", "Arial"):
        if name in available:
            _FONT_FAMILY = name
            return name
    _FONT_FAMILY = "TkDefaultFont"
    return _FONT_FAMILY


def icon_font_family(root: tk.Misc | None = None) -> str:
    available = set(tkfont.families(root))
    for name in ("Segoe UI Symbol", "Segoe UI Emoji", "DejaVu Sans", "Arial Unicode MS"):
        if name in available:
            return name
    return font_family(root)


def fonts(root: tk.Misc | None = None) -> dict[str, tuple]:
    fam = font_family(root)
    return {
        "base": (fam, 10),
        "small": (fam, 9),
        "bold": (fam, 10, "bold"),
        "title": (fam, 18, "bold"),
        "heading": (fam, 12, "bold"),
        "subtitle": (fam, 10),
        "big_number": (fam, 17, "bold"),
        "mono": ("Consolas" if sys.platform == "win32" else "DejaVu Sans Mono", 9),
        "icon": (icon_font_family(root), 14),
        "icon_small": (icon_font_family(root), 11),
    }


# ---------------------------------------------------------------- estilos ttk
def apply_style(root: tk.Tk) -> None:
    """Configura o ttk para o visual escuro (tema 'clam' como base, pois aceita todas as cores)."""
    f = fonts(root)
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(bg=BG)
    root.option_add("*Font", f["base"])
    # Listas de seleção (dropdown do Combobox) também em tema escuro
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_DARK)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*TCombobox*Listbox.font", f["base"])

    style.configure(".", background=PANEL, foreground=TEXT, fieldbackground=FIELD, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, troughcolor=BG, font=f["base"], focuscolor=PANEL)

    style.configure("TFrame", background=PANEL)
    style.configure("TLabel", background=PANEL, foreground=TEXT)

    # Campos de texto e listas suspensas
    style.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT, bordercolor=BORDER,
                    lightcolor=FIELD, darkcolor=FIELD, padding=(6, 5))
    style.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)],
              darkcolor=[("focus", ACCENT)])
    style.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=TEXT, arrowcolor=TEXT_DIM,
                    bordercolor=BORDER, lightcolor=FIELD, darkcolor=FIELD, padding=(6, 4))
    style.map("TCombobox",
              fieldbackground=[("readonly", FIELD), ("disabled", PANEL)],
              foreground=[("disabled", TEXT_FAINT)],
              bordercolor=[("focus", ACCENT)], arrowcolor=[("hover", TEXT)],
              selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", TEXT)])
    style.configure("TSpinbox", fieldbackground=FIELD, foreground=TEXT, arrowcolor=TEXT_DIM, bordercolor=BORDER,
                    lightcolor=FIELD, darkcolor=FIELD, padding=(6, 4))

    # Caixas de marcar e opções
    for kind in ("TCheckbutton", "TRadiobutton"):
        style.configure(kind, background=PANEL, foreground=TEXT, indicatorbackground=FIELD,
                        indicatorforeground=ACCENT, bordercolor=BORDER)
        style.map(kind, background=[("active", PANEL)], indicatorbackground=[("selected", ACCENT)],
                  foreground=[("disabled", TEXT_FAINT)])

    # Barras de progresso finas, como os medidores do editor de referência
    style.configure("Accent.Horizontal.TProgressbar", troughcolor=FIELD, background=ACCENT, bordercolor=FIELD,
                    lightcolor=ACCENT, darkcolor=ACCENT, thickness=6)
    style.configure("Success.Horizontal.TProgressbar", troughcolor=FIELD, background=SUCCESS, bordercolor=FIELD,
                    lightcolor=SUCCESS, darkcolor=SUCCESS, thickness=6)
    style.configure("Danger.Horizontal.TProgressbar", troughcolor=FIELD, background=DANGER, bordercolor=FIELD,
                    lightcolor=DANGER, darkcolor=DANGER, thickness=6)
    style.configure("Warning.Horizontal.TProgressbar", troughcolor=FIELD, background=WARNING, bordercolor=FIELD,
                    lightcolor=WARNING, darkcolor=WARNING, thickness=6)

    # Barras de rolagem discretas
    style.layout("Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
        ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])   # sem setas
    style.configure("Vertical.TScrollbar", background=BORDER, troughcolor=PANEL, bordercolor=PANEL,
                    arrowcolor=PANEL, lightcolor=BORDER, darkcolor=BORDER, gripcount=0, width=10)
    style.map("Vertical.TScrollbar", background=[("active", BORDER_STRONG)])

    # Tabela (Treeview) usada no analisador e nas listas de arquivos
    style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, bordercolor=BORDER,
                    rowheight=26, borderwidth=0)
    style.configure("Treeview.Heading", background=PANEL_ALT, foreground=TEXT_DIM, bordercolor=BORDER,
                    relief="flat", padding=(8, 5), font=f["small"])
    style.map("Treeview", background=[("selected", SELECTED)], foreground=[("selected", TEXT)])
    style.map("Treeview.Heading", background=[("active", HOVER)])

    style.configure("TSeparator", background=BORDER)
    style.configure("Horizontal.TScale", background=ACCENT, troughcolor=FIELD, bordercolor=BORDER,
                    lightcolor=ACCENT, darkcolor=ACCENT, sliderthickness=14)
    style.map("Horizontal.TScale", background=[("active", ACCENT_HOVER)])
