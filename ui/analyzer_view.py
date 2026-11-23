"""Tela do Analisador de mídia: mostra todos os detalhes técnicos de um arquivo (via FFprobe)."""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog
from typing import Optional

from core.analyzer import ReportSection, build_report, report_to_text
from core.ffprobe import MediaInfo, ProbeError, probe
from ui import theme
from ui.base_view import AppContext, BaseView
from ui.file_list import media_filetypes
from ui.widgets import Button, Card, EmptyState, ScrollFrame, Spinner, run_in_background
from utils.file_utils import format_bitrate, format_duration, format_size, open_in_explorer


class _StatTile(tk.Frame):
    """Número em destaque (como os valores azuis do painel de propriedades de referência)."""

    def __init__(self, parent, label: str, value: str):
        super().__init__(parent, bg=theme.PANEL, highlightbackground=theme.BORDER, highlightthickness=1)
        f = theme.fonts(parent)
        tk.Label(self, text=label, bg=theme.PANEL, fg=theme.TEXT_DIM, font=f["small"]).pack(anchor="w", padx=14,
                                                                                            pady=(10, 0))
        tk.Label(self, text=value, bg=theme.PANEL, fg=theme.ACCENT, font=f["big_number"]).pack(anchor="w", padx=14,
                                                                                               pady=(0, 10))


class AnalyzerView(BaseView):
    key = "analyzer"
    title = "Analisador de mídia"
    accepts_multiple_files = False

    def __init__(self, parent: tk.Misc, app: AppContext):
        super().__init__(parent, app)
        self.info: Optional[MediaInfo] = None
        self._request = 0                       # identifica a análise mais recente (descarta respostas velhas)

        # --- barra superior: escolher arquivo / ações ---
        bar = Card(self, padding=12)
        bar.pack(fill="x")
        row = tk.Frame(bar.body, bg=theme.PANEL)
        row.pack(fill="x")
        Button(row, "Escolher arquivo…", self.browse, style="primary", icon="open").pack(side="left")
        self.path_lbl = tk.Label(row, text="Nenhum arquivo selecionado", bg=theme.PANEL, fg=theme.TEXT_DIM,
                                 font=theme.fonts(self)["base"], anchor="w")
        self.path_lbl.pack(side="left", padx=14, fill="x", expand=True)
        self.spinner = Spinner(row)
        self.spinner.pack(side="left", padx=(0, 10))
        self.folder_btn = Button(row, "Abrir pasta", self._open_folder, style="secondary", icon="folder")
        self.copy_btn = Button(row, "Copiar relatório", self._copy_report, style="secondary")
        self.copy_btn.pack(side="right")
        self.folder_btn.pack(side="right", padx=(0, 8))
        self._set_actions(False)

        # --- área de resultados ---
        self.scroll = ScrollFrame(self, bg=theme.BG)
        self.scroll.pack(fill="both", expand=True, pady=(14, 0))
        self._show_empty()

    # ------------------------------------------------------------------ contrato BaseView
    def accept_files(self, paths: list[str]) -> bool:
        if not paths:
            return False
        if len(paths) > 1:
            self.app.set_status("O analisador mostra um arquivo por vez: abrindo o primeiro da seleção.")
        self.load(paths[0])
        return True

    def on_refresh(self) -> None:
        if self.info:
            self.load(self.info.path)

    # ------------------------------------------------------------------ ações
    def browse(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Escolher arquivo para analisar",
                                          filetypes=media_filetypes("any"))
        if path:
            self.load(path)

    def load(self, path: str) -> None:
        """Analisa o arquivo em segundo plano e exibe o resultado."""
        if not self.app.ffprobe.ok:
            self.require_tools()
            return
        self._request += 1
        request = self._request
        ffprobe_path = self.app.ffprobe_path
        self.path_lbl.configure(text=path, fg=theme.TEXT)
        self.spinner.start()
        self._set_actions(False)

        def done(info: MediaInfo) -> None:
            if request != self._request:
                return
            self.spinner.stop()
            self.info = info
            self._show_report(info)
            self.app.set_status(f"✓ Análise concluída: {info.filename}")

        def failed(exc: Exception) -> None:
            if request != self._request:
                return
            self.spinner.stop()
            self.info = None
            message = str(exc) if isinstance(exc, ProbeError) else f"Erro inesperado: {exc}"
            self._clear()
            EmptyState(self.scroll.inner, "cancel", "Não foi possível analisar este arquivo", message,
                       bg=theme.BG).pack(pady=40)
            self.app.set_status(f"✕ {message}", timeout_ms=10000)

        run_in_background(self, lambda: probe(path, ffprobe_path), done, failed)

    def _set_actions(self, enabled: bool) -> None:
        self.copy_btn.set_enabled(enabled)
        self.folder_btn.set_enabled(enabled)

    def _copy_report(self) -> None:
        if not self.info:
            return
        self.clipboard_clear()
        self.clipboard_append(report_to_text(build_report(self.info)))
        self.app.set_status("✓ Relatório copiado para a área de transferência.")

    def _open_folder(self) -> None:
        if self.info:
            open_in_explorer(self.info.path)

    # ------------------------------------------------------------------ desenho
    def _clear(self) -> None:
        for child in self.scroll.inner.winfo_children():
            child.destroy()

    def _show_empty(self) -> None:
        self._clear()
        EmptyState(self.scroll.inner, "analyzer", "Nenhum arquivo analisado",
                   "Escolha um vídeo ou áudio para ver duração, resolução, codecs, bitrate e muito mais. "
                   "Você também pode usar Ctrl+O.", "Escolher arquivo…", self.browse, bg=theme.BG).pack(pady=50)

    def _show_report(self, info: MediaInfo) -> None:
        self._clear()
        self._set_actions(True)
        inner = self.scroll.inner

        tiles = tk.Frame(inner, bg=theme.BG)
        tiles.pack(fill="x")
        stats = [("Duração", format_duration(info.duration)),
                 ("Resolução", info.resolution_text),
                 ("FPS", self._fps(info)),
                 ("Tamanho", format_size(info.size)),
                 ("Bitrate", format_bitrate(info.bitrate))]
        for n, (label, value) in enumerate(stats):
            tiles.columnconfigure(n, weight=1, uniform="tile")
            _StatTile(tiles, label, value).grid(row=0, column=n, sticky="ew", padx=(0 if n == 0 else 8, 0))

        sections = {s.key: s for s in build_report(info)}
        columns = tk.Frame(inner, bg=theme.BG)
        columns.pack(fill="x", pady=(14, 14))
        columns.columnconfigure((0, 1), weight=1, uniform="col")
        left, right = tk.Frame(columns, bg=theme.BG), tk.Frame(columns, bg=theme.BG)
        left.grid(row=0, column=0, sticky="new", padx=(0, 7))
        right.grid(row=0, column=1, sticky="new", padx=(7, 0))
        self._card(left, sections["file"])
        if "extra" in sections:
            self._card(left, sections["extra"])
        self._card(right, sections["video"])
        self._card(right, sections["audio"])

    @staticmethod
    def _fps(info: MediaInfo) -> str:
        if info.video and info.video.fps:
            return f"{info.video.fps:.2f}".rstrip("0").rstrip(".").replace(".", ",")
        return "—"

    def _card(self, parent: tk.Misc, section: ReportSection) -> None:
        f = theme.fonts(self)
        card = Card(parent, title=section.title)
        card.pack(fill="x", pady=(0, 14))
        if section.note:
            tk.Label(card.body, text=section.note, bg=theme.PANEL, fg=theme.TEXT_DIM, font=f["base"],
                     anchor="w").pack(anchor="w")
        for label, value in section.rows:
            row = tk.Frame(card.body, bg=theme.PANEL)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, bg=theme.PANEL, fg=theme.TEXT_DIM, font=f["base"], width=19,
                     anchor="w").pack(side="left", anchor="n")
            tk.Label(row, text=value, bg=theme.PANEL, fg=theme.TEXT, font=f["base"], anchor="w", justify="left",
                     wraplength=230).pack(side="left", fill="x", expand=True)
