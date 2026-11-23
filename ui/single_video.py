"""Base das telas que trabalham com UM vídeo por vez (extrator de frames e cortador)."""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog
from typing import Optional

from core.analyzer import one_line_summary
from core.ffprobe import MediaInfo, ProbeError, probe
from ui import theme
from ui.base_view import AppContext, BaseView
from ui.file_list import media_filetypes
from ui.widgets import Button, Card, ScrollFrame, Spinner, message_dialog, run_in_background


class SingleVideoView(BaseView):
    """Mostra o seletor de vídeo no topo e chama ``on_video_loaded`` quando a análise termina.

    As subclasses constroem o resto da tela em ``self.page.inner``.
    """

    accepts_multiple_files = False

    def __init__(self, parent: tk.Misc, app: AppContext):
        super().__init__(parent, app)
        self.info: Optional[MediaInfo] = None
        self._request = 0                          # descarta respostas de análises antigas
        self.page = ScrollFrame(self, bg=theme.BG)
        self.page.pack(fill="both", expand=True)

        card = Card(self.page.inner, title="1 · Vídeo")
        card.pack(fill="x", pady=(0, 14))
        row = tk.Frame(card.body, bg=theme.PANEL)
        row.pack(fill="x")
        Button(row, "Escolher vídeo…", self.browse, style="primary", icon="open").pack(side="left")
        self.path_lbl = tk.Label(row, text="Nenhum vídeo selecionado", bg=theme.PANEL, fg=theme.TEXT_DIM,
                                 font=theme.fonts(self)["base"], anchor="w")
        self.path_lbl.pack(side="left", padx=14, fill="x", expand=True)
        self.spinner = Spinner(row)
        self.spinner.pack(side="right")
        self.info_lbl = tk.Label(card.body, text="Use Ctrl+O ou o botão acima para escolher um vídeo.",
                                 bg=theme.PANEL, fg=theme.TEXT_DIM, font=theme.fonts(self)["small"], anchor="w")
        self.info_lbl.pack(fill="x", pady=(8, 0))

    # ------------------------------------------------------------------ contrato BaseView
    def accept_files(self, paths: list[str]) -> bool:
        if not paths:
            return False
        if len(paths) > 1:
            self.app.set_status("Esta ferramenta usa um vídeo por vez: abrindo o primeiro da seleção.")
        self.load(paths[0])
        return True

    def on_refresh(self) -> None:
        if self.info:
            self.load(self.info.path)

    # ------------------------------------------------------------------ carregamento
    def browse(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Escolher vídeo", filetypes=media_filetypes("video"))
        if path:
            self.load(path)

    def load(self, path: str) -> None:
        if not self.app.ffprobe.ok:
            self.require_tools()
            return
        self._request += 1
        request = self._request
        ffprobe_path = self.app.ffprobe_path
        self.path_lbl.configure(text=path, fg=theme.TEXT)
        self.info_lbl.configure(text="Analisando o arquivo…", fg=theme.TEXT_DIM)
        self.spinner.start()

        def done(info: MediaInfo) -> None:
            if request != self._request:
                return
            self.spinner.stop()
            if not info.has_video:
                self._reject(f"“{info.filename}” não tem trilha de vídeo.")
                return
            self.info = info
            self.info_lbl.configure(text=f"{info.filename}  ·  {one_line_summary(info)}", fg=theme.ACCENT)
            self.on_video_loaded(info)

        def failed(exc: Exception) -> None:
            if request != self._request:
                return
            self.spinner.stop()
            self._reject(str(exc) if isinstance(exc, ProbeError) else f"Erro inesperado: {exc}")

        run_in_background(self, lambda: probe(path, ffprobe_path), done, failed)

    def _reject(self, message: str) -> None:
        self.info = None
        self.path_lbl.configure(text="Nenhum vídeo selecionado", fg=theme.TEXT_DIM)
        self.info_lbl.configure(text=message, fg=theme.DANGER)
        self.on_video_cleared()
        message_dialog(self, "Não foi possível usar este arquivo", message, kind="warning")

    # ------------------------------------------------------------------ ganchos das subclasses
    def on_video_loaded(self, info: MediaInfo) -> None:
        """Chamado na thread do Tkinter quando um vídeo válido foi analisado."""

    def on_video_cleared(self) -> None:
        """Chamado quando o arquivo escolhido não pôde ser usado."""
