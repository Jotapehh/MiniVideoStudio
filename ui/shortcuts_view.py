"""Página “Atalhos de teclado”: lista todos os atalhos e permite personalizá-los."""
from __future__ import annotations

import sys
import tkinter as tk
from typing import Optional

from ui import theme
from ui.base_view import AppContext
from ui.widgets import Button, Card, Dialog, message_dialog
from utils.shortcuts import (Shortcut, build_sequence, display_name, effective_shortcuts, find_conflict,
                             validate_sequence, SHORTCUTS)


def event_modifiers(state: int) -> tuple[bool, bool, bool]:
    """(ctrl, shift, alt) a partir do campo ``state`` de um evento de teclado do Tk (varia por plataforma)."""
    alt_mask = 0x20000 if sys.platform == "win32" else 0x8
    return bool(state & 0x4), bool(state & 0x1), bool(state & alt_mask)


class CaptureDialog(Dialog):
    """Pede ao usuário que pressione a nova combinação de teclas."""

    def __init__(self, parent: tk.Misc, app: AppContext, shortcut: Shortcut):
        super().__init__(parent, "Alterar atalho", width=460)
        self.app, self.shortcut = app, shortcut
        f = theme.fonts(self)
        tk.Label(self.body, text=f"Novo atalho para: {shortcut.label}", bg=theme.PANEL, fg=theme.TEXT,
                 font=f["heading"], anchor="w").pack(fill="x")
        tk.Label(self.body, text="Pressione a combinação de teclas desejada (por exemplo, Ctrl + Shift + K).",
                 bg=theme.PANEL, fg=theme.TEXT_DIM, font=f["base"], wraplength=410, justify="left",
                 anchor="w").pack(fill="x", pady=(4, 12))
        self.shown = tk.Label(self.body, text="Aguardando…", bg=theme.FIELD, fg=theme.ACCENT, font=f["heading"],
                              pady=14)
        self.shown.pack(fill="x")
        self.error = tk.Label(self.body, text="", bg=theme.PANEL, fg=theme.DANGER, font=f["small"], wraplength=410,
                              justify="left", anchor="w")
        self.error.pack(fill="x", pady=(8, 0))
        self.add_button("Cancelar", None)
        self.bind("<KeyPress>", self._on_key)
        self.bind("<Escape>", self._on_key)                 # Esc também pode ser um atalho
        self.bind("<Tab>", self._on_key)

    def _on_key(self, event) -> str:
        ctrl, shift, alt = event_modifiers(event.state)
        sequence = build_sequence(event.keysym, ctrl, shift, alt)
        if sequence is None:                                # só um modificador pressionado até agora
            self.shown.configure(text=" + ".join(p for p, on in (("Ctrl", ctrl), ("Alt", alt), ("Shift", shift)) if on)
                                 or "Aguardando…")
            return "break"
        self.shown.configure(text=display_name(sequence))
        problem = validate_sequence(sequence)
        if not problem:
            conflict = find_conflict(sequence, self.app.config.get("shortcuts"), ignore_id=self.shortcut.id)
            if conflict:
                problem = f"Esta combinação já é usada por “{conflict.label}”. Escolha outra."
        if problem:
            self.error.configure(text=problem)
            return "break"
        self.close(sequence)
        return "break"


class ShortcutsPanel(tk.Frame):
    """Tabela de atalhos agrupada por categoria, com botões para alterar e restaurar."""

    def __init__(self, parent: tk.Misc, app: AppContext):
        super().__init__(parent, bg=theme.BG)
        self.app = app
        f = theme.fonts(self)
        top = tk.Frame(self, bg=theme.BG)
        top.pack(fill="x", pady=(0, 10))
        tk.Label(top, text="Clique em “Alterar” e pressione a nova combinação. Os atalhos não funcionam enquanto "
                 "você digita em um campo de texto (exceto F1, Esc e Ctrl+Q).", bg=theme.BG, fg=theme.TEXT_DIM,
                 font=f["small"], wraplength=560, justify="left", anchor="w").pack(side="left", fill="x", expand=True)
        Button(top, "Restaurar todos os padrões", self._restore_all, style="secondary").pack(side="right")
        self.cards = tk.Frame(self, bg=theme.BG)
        self.cards.pack(fill="x")
        self.refresh()

    def refresh(self) -> None:
        for child in self.cards.winfo_children():
            child.destroy()
        overrides = self.app.config.get("shortcuts")
        f = theme.fonts(self)
        categories: dict[str, list[Shortcut]] = {}
        for s in effective_shortcuts(overrides):
            categories.setdefault(s.category, []).append(s)
        defaults = {s.id: s.sequence for s in SHORTCUTS}
        for category, items in categories.items():
            card = Card(self.cards, title=category)
            card.pack(fill="x", pady=(0, 12))
            for s in items:
                row = tk.Frame(card.body, bg=theme.PANEL)
                row.pack(fill="x", pady=3)
                tk.Label(row, text=s.label, bg=theme.PANEL, fg=theme.TEXT, font=f["base"], anchor="w").pack(
                    side="left", fill="x", expand=True)
                custom = s.sequence != defaults[s.id]
                if custom:
                    btn = Button(row, "Restaurar", lambda sid=s.id: self._restore(sid), style="ghost")
                    btn.configure(padx=8, pady=2)
                    btn.pack(side="right", padx=(6, 0))
                change = Button(row, "Alterar", lambda sc=s: self._change(sc), style="secondary")
                change.configure(padx=10, pady=2)
                change.pack(side="right", padx=(6, 0))
                tk.Label(row, text=display_name(s.sequence), bg=theme.FIELD, fg=theme.ACCENT if custom else theme.TEXT,
                         font=f["mono"], padx=10, pady=3, width=18).pack(side="right")

    # ------------------------------------------------------------------ ações
    def _save(self, overrides: dict) -> None:
        self.app.config.set("shortcuts", overrides)
        self.app.rebind_shortcuts()
        self.refresh()

    def _change(self, shortcut: Shortcut) -> None:
        sequence: Optional[str] = CaptureDialog(self, self.app, shortcut).show()
        if not sequence:
            return
        overrides = self.app.config.get("shortcuts")
        default = next(s.sequence for s in SHORTCUTS if s.id == shortcut.id)
        if sequence == default:
            overrides.pop(shortcut.id, None)
        else:
            overrides[shortcut.id] = sequence
        self._save(overrides)
        self.app.set_status(f"✓ Atalho de “{shortcut.label}” alterado para {display_name(sequence)}.")

    def _restore(self, shortcut_id: str) -> None:
        overrides = self.app.config.get("shortcuts")
        overrides.pop(shortcut_id, None)
        self._save(overrides)

    def _restore_all(self) -> None:
        if not self.app.config.get("shortcuts"):
            self.app.set_status("Todos os atalhos já estão no padrão.")
            return
        if message_dialog(self, "Restaurar atalhos", "Voltar todos os atalhos de teclado ao padrão?", kind="question",
                          confirm_text="Restaurar", cancel_text="Cancelar", danger=True):
            self._save({})
