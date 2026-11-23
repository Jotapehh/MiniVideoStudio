"""Tela do Cortador de vídeo."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from core import converter as cv
from core import cutter as ct
from core.ffmpeg import list_encoders
from core.ffprobe import MediaInfo
from ui import theme
from ui.base_view import AppContext
from ui.single_video import SingleVideoView
from ui.task_panel import TaskPanel
from ui.time_controls import FramePreview, TimeField
from ui.widgets import Button, Card, OutputFolderPicker, PropertyRow, message_dialog
from utils.file_utils import format_duration
from utils.validators import ValidationError, format_time

MODE_LABELS = {ct.MODE_FAST: "Corte rápido (sem recodificar)", ct.MODE_PRECISE: "Corte preciso (recodifica)"}
MODE_HELP = {
    ct.MODE_FAST: "Copia o vídeo sem recomprimir: é quase instantâneo e não perde qualidade, mas o corte só pode "
                  "começar em um “quadro-chave”, então o início pode ficar alguns segundos antes do tempo escolhido.",
    ct.MODE_PRECISE: "Recodifica o trecho: demora mais, mas o início e o fim ficam exatamente nos tempos escolhidos.",
}


class CutterView(SingleVideoView):
    key = "cutter"
    title = "Cortador de vídeo"
    tool_name = "cutter"

    def __init__(self, parent: tk.Misc, app: AppContext):
        super().__init__(parent, app)
        self._encoders = list_encoders(app.ffmpeg_path) if app.ffmpeg.ok else {}
        page = self.page.inner
        self.var_mode = tk.StringVar(value=ct.MODE_FAST)
        self.var_container = tk.StringVar(value="MP4")

        self._build_range_card(page)
        self._build_output_card(page)

        actions = tk.Frame(page, bg=theme.BG)
        actions.pack(fill="x", pady=(0, 14))
        self.cut_btn = Button(actions, "Cortar trecho", self.start, style="primary", icon="cutter")
        self.cut_btn.pack(side="left")
        TaskPanel(page, app.tasks, kinds={ct.KIND}, title="Cortes", height=190).pack(fill="x", pady=(0, 10))

        self._restore_settings()
        self._set_enabled(False)

    # ================================================================== construção
    def _build_range_card(self, page: tk.Misc) -> None:
        card = Card(page, title="2 · Trecho a manter")
        card.pack(fill="x", pady=(0, 14))
        cols = tk.Frame(card.body, bg=theme.PANEL)
        cols.pack(fill="x")
        cols.columnconfigure((0, 1), weight=1, uniform="r")
        self.start_prev = self._time_column(cols, 0, "Início do trecho", "start")
        self.end_prev = self._time_column(cols, 1, "Fim do trecho", "end")
        self.length_lbl = tk.Label(card.body, text="", bg=theme.PANEL, fg=theme.ACCENT, font=theme.fonts(self)["heading"],
                                   anchor="w")
        self.length_lbl.pack(fill="x", pady=(12, 0))

    def _time_column(self, parent: tk.Misc, column: int, title: str, which: str) -> FramePreview:
        box = tk.Frame(parent, bg=theme.PANEL)
        box.grid(row=0, column=column, sticky="nw", padx=(0 if column == 0 else 14, 0))
        tk.Label(box, text=title, bg=theme.PANEL, fg=theme.TEXT, font=theme.fonts(self)["bold"], anchor="w").pack(
            fill="x", pady=(0, 6))
        preview = FramePreview(box, lambda: self.app.ffmpeg_path, width=300, height=170,
                               placeholder="Escolha um vídeo")
        preview.pack(anchor="w")
        field = TimeField(box, on_change=lambda seconds, w=which: self._on_time_change(w, seconds), scale_length=140)
        field.pack(fill="x", pady=(8, 0))
        setattr(self, f"{which}_time", field)
        return preview

    def _build_output_card(self, page: tk.Misc) -> None:
        card = Card(page, title="3 · Modo de corte e formato")
        card.pack(fill="x", pady=(0, 14))
        row = PropertyRow(card.body, "Modo de corte", "Escolha entre velocidade (rápido) e precisão (preciso).",
                          label_width=150)
        row.pack(fill="x", pady=4)
        for mode, label in MODE_LABELS.items():
            ttk.Radiobutton(row.body, text=label, value=mode, variable=self.var_mode,
                            command=self._on_option_change).pack(anchor="w", pady=1)
        self.mode_help = tk.Label(card.body, text="", bg=theme.PANEL, fg=theme.TEXT_FAINT, font=theme.fonts(self)["small"],
                                  wraplength=640, justify="left", anchor="w")
        self.mode_help.pack(fill="x", padx=(150, 0), pady=(0, 6))
        row = PropertyRow(card.body, "Formato de saída", "O tipo de arquivo gerado. No corte rápido, o formato precisa "
                          "ser compatível com o vídeo original; no preciso, qualquer um funciona.", label_width=150)
        row.pack(fill="x", pady=4)
        self.cb_container = ttk.Combobox(row.body, textvariable=self.var_container, state="readonly", width=16,
                                         values=[c.label for c in cv.CONTAINERS.values()])
        self.cb_container.pack(side="left")
        self.cb_container.bind("<<ComboboxSelected>>", lambda e: self._on_option_change())
        self.hint_lbl = tk.Label(card.body, text="", bg=theme.PANEL, fg=theme.WARNING, font=theme.fonts(self)["small"],
                                 wraplength=640, justify="left", anchor="w")
        self.hint_lbl.pack(fill="x", padx=(150, 0))
        tk.Frame(card.body, bg=theme.BORDER, height=1).pack(fill="x", pady=(10, 8))
        self.out = OutputFolderPicker(card.body, default_dir=self.app.config.get("export_dir"),
                                      same_label="Salvar na mesma pasta do vídeo", label_width=150)
        self.out.pack(fill="x")
        self._on_option_change()

    # ================================================================== estado
    def _container_id(self) -> str:
        return next((c.id for c in cv.CONTAINERS.values() if c.label == self.var_container.get()), "mp4")

    def _set_enabled(self, enabled: bool) -> None:
        self.start_time.set_enabled(enabled)
        self.end_time.set_enabled(enabled)
        self.cut_btn.set_enabled(enabled)

    def on_video_loaded(self, info: MediaInfo) -> None:
        duration = info.duration or 0.0
        for field in (self.start_time, self.end_time):
            field.set_duration(duration)
        self.start_time.set(0.0, notify=False)
        self.end_time.set(duration, notify=False)
        self.var_container.set(cv.CONTAINERS[ct.default_container(info)].label)     # mantém o formato do original
        self._set_enabled(True)
        self.start_prev.show(info, 0.0, delay_ms=0)
        self.end_prev.show(info, duration, delay_ms=0)
        self._on_option_change()
        self._update_length()

    def on_video_cleared(self) -> None:
        self._set_enabled(False)
        self.start_prev.clear()
        self.end_prev.clear()
        self.length_lbl.configure(text="")

    def _on_time_change(self, which: str, seconds: float) -> None:
        if self.info:
            (self.start_prev if which == "start" else self.end_prev).show(self.info, seconds)
            self._update_length()

    def _update_length(self) -> None:
        if not self.info:
            return
        try:
            start, end = self.start_time.get(), self.end_time.get()
        except ValidationError as exc:
            self.length_lbl.configure(text=str(exc), fg=theme.DANGER)
            return
        if end - start < ct.MIN_CLIP:
            self.length_lbl.configure(text="O tempo final precisa ser maior que o inicial.", fg=theme.DANGER)
        else:
            self.length_lbl.configure(
                text=f"Duração do trecho: {format_time(end - start)}   (de {format_duration(self.info.duration)} no total)",
                fg=theme.ACCENT)

    def _on_option_change(self) -> None:
        """Atualiza o texto explicativo e avisa cedo se o corte rápido não serve para o formato escolhido."""
        self.mode_help.configure(text=MODE_HELP[self.var_mode.get()])
        hint = ""
        if self.info and self.var_mode.get() == ct.MODE_FAST:
            try:
                cv.validate_options(cv.ConvertOptions(container=self._container_id(), video_codec="copy",
                                                      audio_codec="copy"), self.info)
            except ValidationError as exc:
                hint = f"⚠ {exc}"
        self.hint_lbl.configure(text=hint)

    # ================================================================== ações
    def collect_options(self) -> ct.CutOptions:
        return ct.CutOptions(start=self.start_time.get(), end=self.end_time.get(), mode=self.var_mode.get(),
                             container=self._container_id(), out_dir=self.out.resolve())

    def start(self) -> None:
        if not self.info or not self.require_tools():
            return
        try:
            job = ct.build_job(self.info, self.collect_options(), self._encoders)
        except ValidationError as exc:
            message_dialog(self, "Confira o corte", str(exc), kind="warning")
            return
        self.submit(job)

    # ================================================================== Ctrl+S
    def on_save(self) -> bool:
        self.app.config.set_tool_settings(self.tool_name, {
            "mode": self.var_mode.get(), "outdir": self.out.var_folder.get(), "same_folder": self.out.var_same.get()})
        return True

    def _restore_settings(self) -> None:
        saved = self.app.config.get_tool_settings(self.tool_name)
        if saved.get("mode") in MODE_LABELS:
            self.var_mode.set(saved["mode"])
        if isinstance(saved.get("outdir"), str) and saved["outdir"]:
            self.out.var_folder.set(saved["outdir"])
        self.out.var_same.set(bool(saved.get("same_folder", False)))
        self._on_option_change()
