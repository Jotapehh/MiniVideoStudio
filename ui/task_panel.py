"""Painel que lista as tarefas da fila com progresso, tempo e ações."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

from core.task_manager import Job, TaskManager, TaskState
from ui import theme
from ui.theme import ICONS, STATE_COLORS
from ui.widgets import Button, Card, EmptyState, ScrollFrame, message_dialog
from utils.file_utils import format_size, format_duration, open_in_explorer

_BAR_STYLE = {
    TaskState.WAITING: "Accent.Horizontal.TProgressbar",
    TaskState.RUNNING: "Accent.Horizontal.TProgressbar",
    TaskState.DONE: "Success.Horizontal.TProgressbar",
    TaskState.CANCELLED: "Warning.Horizontal.TProgressbar",
    TaskState.ERROR: "Danger.Horizontal.TProgressbar",
}


def _shorten(text: str, limit: int = 56) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


class TaskRow(tk.Frame):
    """Uma tarefa: nome, tipo, estado, barra de progresso, tempo, mensagem e botões."""

    def __init__(self, parent, job: Job, manager: TaskManager):
        super().__init__(parent, bg=theme.PANEL_ALT, highlightbackground=theme.BORDER, highlightthickness=1)
        self.job, self.manager = job, manager
        f = theme.fonts(parent)
        pad = {"padx": 12}

        top = tk.Frame(self, bg=theme.PANEL_ALT)
        top.pack(fill="x", pady=(9, 4), **pad)
        self.state_lbl = tk.Label(top, text="", bg=theme.PANEL_ALT, font=f["small"], width=12, anchor="w")
        self.state_lbl.pack(side="left")
        self.name_lbl = tk.Label(top, text=_shorten(job.name), bg=theme.PANEL_ALT, fg=theme.TEXT, font=f["bold"],
                                 anchor="w")
        self.name_lbl.pack(side="left")
        tk.Label(top, text=f"· {job.kind}", bg=theme.PANEL_ALT, fg=theme.TEXT_FAINT, font=f["small"]).pack(
            side="left", padx=(8, 0))
        self.buttons = tk.Frame(top, bg=theme.PANEL_ALT)
        self.buttons.pack(side="right")
        self.elapsed_lbl = tk.Label(top, text="00:00", bg=theme.PANEL_ALT, fg=theme.TEXT_DIM, font=f["small"],
                                    width=8, anchor="e")
        self.elapsed_lbl.pack(side="right", padx=(0, 10))

        mid = tk.Frame(self, bg=theme.PANEL_ALT)
        mid.pack(fill="x", **pad)
        self.bar = ttk.Progressbar(mid, mode="determinate", maximum=100, style=_BAR_STYLE[job.state])
        self.bar.pack(side="left", fill="x", expand=True)
        self.pct_lbl = tk.Label(mid, text="0%", bg=theme.PANEL_ALT, fg=theme.ACCENT, font=f["small"], width=6,
                                anchor="e")
        self.pct_lbl.pack(side="right")

        self.msg_lbl = tk.Label(self, text="", bg=theme.PANEL_ALT, fg=theme.TEXT_DIM, font=f["small"], anchor="w",
                                justify="left", wraplength=640)
        self.msg_lbl.pack(fill="x", pady=(4, 9), **pad)
        self._mode = "determinate"
        self.refresh()

    # ------------------------------------------------------------------ atualização
    def refresh(self) -> None:
        job = self.job
        color = STATE_COLORS[job.state.value]
        self.state_lbl.configure(text=f"● {job.state_label}", fg=color)
        self.elapsed_lbl.configure(text=format_duration(job.elapsed))

        indeterminate = job.state == TaskState.RUNNING and job.indeterminate
        if indeterminate and self._mode != "indeterminate":
            self.bar.configure(mode="indeterminate")
            self.bar.start(15)
            self._mode = "indeterminate"
        elif not indeterminate and self._mode == "indeterminate":
            self.bar.stop()
            self.bar.configure(mode="determinate")
            self._mode = "determinate"
        self.bar.configure(style=_BAR_STYLE[job.state])
        if self._mode == "determinate":
            self.bar["value"] = job.progress * 100
        self.pct_lbl.configure(text="" if indeterminate else f"{job.progress * 100:.0f}%",
                               fg=color if job.state != TaskState.WAITING else theme.TEXT_DIM)

        message = job.message
        if job.state == TaskState.DONE and job.output_size:
            message = f"Concluído · arquivo gerado: {format_size(job.output_size)}"
            if job.input_size:
                message += f" (original: {format_size(job.input_size)})"
                if job.extra.get("compare"):          # compressão: mostra a economia de espaço
                    saved = (1 - job.output_size / job.input_size) * 100
                    message += (f" · economia de {saved:.0f}%" if saved >= 0
                                else f" · ficou {abs(saved):.0f}% MAIOR que o original")
        self.msg_lbl.configure(text=message, fg=theme.DANGER if job.state == TaskState.ERROR else theme.TEXT_DIM)
        self._rebuild_buttons()

    def _rebuild_buttons(self) -> None:
        state = self.job.state
        key = (state, bool(self._open_target()), bool(self.job.detail))
        if getattr(self, "_buttons_key", None) == key:
            return                                   # nada mudou: evita recriar botões a cada 100 ms
        self._buttons_key = key
        for child in self.buttons.winfo_children():
            child.destroy()

        def small(text, command, style="ghost"):
            b = Button(self.buttons, text, command, style=style)
            b.configure(padx=8, pady=2, bg=theme.PANEL_ALT)
            b._bg = theme.PANEL_ALT
            b.pack(side="left", padx=(4, 0))

        if state in (TaskState.WAITING, TaskState.RUNNING):
            small(f"{ICONS['cancel']} Cancelar", lambda: self.manager.cancel(self.job.id))
        else:
            if state == TaskState.DONE and self._open_target():
                small(f"{ICONS['folder']} Abrir pasta", lambda: open_in_explorer(self._open_target()))
            if state == TaskState.ERROR:
                small("Detalhes", self._show_details)
            small(ICONS["remove"], lambda: self.manager.remove(self.job.id))

    def _open_target(self) -> str:
        """Arquivo ou pasta que o botão 'Abrir pasta' revela."""
        return self.job.output_path or self.job.extra.get("open_path") or ""

    def _show_details(self) -> None:
        message_dialog(self, "Detalhes do erro", self.job.message, kind="error",
                       detail=self.job.detail or "Sem detalhes técnicos disponíveis.")


class TaskPanel(Card):
    """Lista de tarefas. ``kinds`` limita a lista a certos tipos de operação (ex.: {"Conversão"})."""

    def __init__(self, parent, manager: TaskManager, kinds: Optional[set[str]] = None, title: str = "Tarefas",
                 height: int = 220):
        super().__init__(parent, title=title, padding=12)
        self.manager, self.kinds = manager, kinds
        self._rows: dict[int, TaskRow] = {}

        header_btn = Button(self.header_actions, "Limpar finalizadas", manager.clear_finished, style="ghost")
        header_btn.configure(padx=8, pady=2)
        header_btn.pack()

        self.scroll = ScrollFrame(self.body)
        self.scroll.pack(fill="both", expand=True)
        self.scroll.configure(height=height)
        self.scroll.canvas.configure(height=height)
        self.empty = EmptyState(self.scroll.inner, "folder", "Nenhuma tarefa por enquanto",
                                "Quando você iniciar uma operação, ela aparece aqui com o progresso real.")
        self.empty.pack(fill="x")

        for job in manager.jobs:
            self._add_row(job)
        self._unsubscribe = manager.subscribe(self._on_event)
        self._tick()

    # ------------------------------------------------------------------ eventos
    def _matches(self, job: Job) -> bool:
        return self.kinds is None or job.kind in self.kinds

    def _on_event(self, event: str, job: Job) -> None:
        if not self._matches(job):
            return
        if event == "added":
            self._add_row(job)
        elif event == "removed":
            row = self._rows.pop(job.id, None)
            if row:
                row.destroy()
            self._toggle_empty()
        elif job.id in self._rows:
            self._rows[job.id].refresh()
        else:
            self._add_row(job)

    def _add_row(self, job: Job) -> None:
        if not self._matches(job) or job.id in self._rows:
            return
        row = TaskRow(self.scroll.inner, job, self.manager)
        row.pack(fill="x", pady=(0, 6))
        self._rows[job.id] = row
        self._toggle_empty()

    def _toggle_empty(self) -> None:
        if self._rows:
            self.empty.pack_forget()
        elif not self.empty.winfo_ismapped():
            self.empty.pack(fill="x")

    def _tick(self) -> None:
        """Atualiza o tempo decorrido das tarefas em execução."""
        for row in self._rows.values():
            if row.job.state == TaskState.RUNNING:
                row.elapsed_lbl.configure(text=format_duration(row.job.elapsed))
        self._after = self.after(500, self._tick)

    def destroy(self) -> None:
        self._unsubscribe()
        try:
            self.after_cancel(self._after)
        except (AttributeError, ValueError, tk.TclError):
            pass
        super().destroy()
