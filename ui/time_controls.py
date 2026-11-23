"""Controles compartilhados pelo extrator de frames e pelo cortador: campo de tempo e pré-visualização."""
from __future__ import annotations

import os
import shutil
import tempfile
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from core.ffprobe import MediaInfo
from core.frames import FrameError, clamp_time, render_preview
from ui import theme
from ui.widgets import Spinner, run_in_background
from utils.validators import ValidationError, format_time, parse_time


class TimeField(tk.Frame):
    """Instante de tempo: campo de texto (HH:MM:SS.mmm) + controle deslizante, sempre sincronizados."""

    def __init__(self, parent, on_change: Optional[Callable[[float], None]] = None, scale_length: int = 240):
        super().__init__(parent, bg=theme.PANEL)
        self.on_change = on_change
        self.duration = 0.0
        self._syncing = False
        self.var = tk.StringVar(value=format_time(0))
        self.scale_var = tk.DoubleVar(value=0.0)
        self.entry = ttk.Entry(self, textvariable=self.var, width=13, justify="center")
        self.entry.pack(side="left")
        self.scale = ttk.Scale(self, from_=0, to=1, orient="horizontal", length=scale_length,
                               variable=self.scale_var, command=self._on_scale)
        self.scale.pack(side="left", padx=(10, 0), fill="x", expand=True)
        self.entry.bind("<Return>", lambda e: self._commit())
        self.entry.bind("<FocusOut>", lambda e: self._commit())

    # ------------------------------------------------------------------ API
    def set_duration(self, duration: float) -> None:
        self.duration = max(0.0, duration or 0.0)
        self.scale.configure(to=max(self.duration, 0.001))

    def set(self, seconds: float, notify: bool = True) -> None:
        seconds = max(0.0, min(seconds, self.duration or seconds))
        self._syncing = True
        try:
            self.var.set(format_time(seconds))
            self.scale_var.set(seconds)
        finally:
            self._syncing = False
        if notify and self.on_change:
            self.on_change(seconds)

    def get(self) -> float:
        """Tempo digitado em segundos, dentro de 0…duração. Levanta ValidationError se for inválido."""
        value = parse_time(self.var.get())
        if self.duration and value > self.duration + 0.001:
            raise ValidationError(f"O tempo {format_time(value)} passa da duração do vídeo "
                                  f"({format_time(self.duration)}).")
        return value

    def set_enabled(self, enabled: bool) -> None:
        self.entry.configure(state="normal" if enabled else "disabled")
        self.scale.configure(state="normal" if enabled else "disabled")

    # ------------------------------------------------------------------ eventos
    def _on_scale(self, _value=None) -> None:
        if self._syncing:
            return
        seconds = self.scale_var.get()
        self._syncing = True
        try:
            self.var.set(format_time(seconds))
        finally:
            self._syncing = False
        if self.on_change:
            self.on_change(seconds)

    def _commit(self) -> None:
        """Aplica o texto digitado: valores fora do vídeo são ajustados e textos inválidos revertidos."""
        try:
            seconds = parse_time(self.var.get())
        except ValidationError:
            self.set(self.scale_var.get(), notify=False)       # volta ao último valor válido
            return
        seconds = min(seconds, self.duration) if self.duration else seconds
        changed = abs(seconds - self.scale_var.get()) > 0.0005
        self.set(seconds, notify=changed)                      # só avisa quem escuta se o valor mudou


class FramePreview(tk.Frame):
    """Mostra o frame de um instante do vídeo, gerado pelo FFmpeg em segundo plano (com 'debounce')."""

    def __init__(self, parent, ffmpeg_path_getter: Callable[[], str], width: int = 480, height: int = 270,
                 placeholder: str = "Escolha um vídeo para ver a pré-visualização"):
        super().__init__(parent, bg=theme.PANEL)
        self._ffmpeg_path = ffmpeg_path_getter
        self.size = (width, height)
        self.placeholder = placeholder
        self.canvas = tk.Canvas(self, width=width, height=height, bg="#0e0e0e", highlightthickness=1,
                                highlightbackground=theme.BORDER)
        self.canvas.pack()
        self.spinner = Spinner(self.canvas, size=26, bg="#0e0e0e")
        self._spinner_window = self.canvas.create_window(width - 22, 22, window=self.spinner, state="hidden")
        self._photo: Optional[tk.PhotoImage] = None
        self._tmp = tempfile.mkdtemp(prefix="mvs_preview_")
        self._counter = 0
        self._request = 0
        self._debounce: Optional[str] = None
        self.last_error = ""
        self.clear()

    # ------------------------------------------------------------------ API
    def clear(self, text: Optional[str] = None) -> None:
        self._request += 1
        self._photo = None
        self.canvas.delete("content")
        self.canvas.create_text(self.size[0] // 2, self.size[1] // 2, text=text or self.placeholder,
                                fill=theme.TEXT_FAINT, font=theme.fonts(self)["base"], tags="content",
                                width=self.size[0] - 40, justify="center")

    def show(self, info: MediaInfo, seconds: float, delay_ms: int = 250) -> None:
        """Agenda a geração da imagem; chamadas seguidas (arrastar o controle) só geram a última."""
        if self._debounce:
            self.after_cancel(self._debounce)
        seconds = clamp_time(info, seconds)
        self._debounce = self.after(delay_ms, lambda: self._render(info, seconds))

    def _render(self, info: MediaInfo, seconds: float) -> None:
        self._debounce = None
        self._request += 1
        request = self._request
        self._counter += 1
        out = os.path.join(self._tmp, f"p{self._counter}.png")
        ffmpeg_path = self._ffmpeg_path()
        self.canvas.itemconfigure(self._spinner_window, state="normal")
        self.spinner.start()

        def done(path: str) -> None:
            if request != self._request:
                self._remove(path)
                return
            self._stop_spinner()
            try:
                photo = tk.PhotoImage(file=path)
            except tk.TclError:
                self._show_error("Não foi possível exibir a imagem.")
                return
            finally:
                self._remove(path)
            self.last_error = ""
            self._photo = photo                         # mantém a referência (senão o Tk apaga a imagem)
            self.canvas.delete("content")
            self.canvas.create_image(self.size[0] // 2, self.size[1] // 2, image=photo, tags="content")

        def failed(exc: Exception) -> None:
            if request == self._request:
                self._stop_spinner()
                self._show_error(str(exc) if isinstance(exc, FrameError) else f"Erro: {exc}")

        run_in_background(self, lambda: render_preview(info, seconds, out, ffmpeg_path, *self.size), done, failed)

    def _stop_spinner(self) -> None:
        self.spinner.stop()
        self.canvas.itemconfigure(self._spinner_window, state="hidden")

    def _show_error(self, message: str) -> None:
        self.last_error = message
        self.clear(message)

    @staticmethod
    def _remove(path: str) -> None:
        try:
            os.remove(path)
        except OSError:
            pass

    def destroy(self) -> None:
        self._request += 1
        if self._debounce:
            try:
                self.after_cancel(self._debounce)
            except tk.TclError:
                pass
        shutil.rmtree(self._tmp, ignore_errors=True)
        super().destroy()
