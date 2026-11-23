"""Tela do Extrator de frames: uma imagem de um instante, ou várias em intervalos regulares."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from core import frames as fr
from core.ffprobe import MediaInfo
from ui import theme
from ui.base_view import AppContext
from ui.single_video import SingleVideoView
from ui.task_panel import TaskPanel
from ui.time_controls import FramePreview, TimeField
from ui.widgets import Button, Card, OutputFolderPicker, PropertyRow, message_dialog
from utils.file_utils import format_duration
from utils.validators import ValidationError, parse_float


class FramesView(SingleVideoView):
    key = "frames"
    title = "Extrator de frames"
    tool_name = "frames"

    def __init__(self, parent: tk.Misc, app: AppContext):
        super().__init__(parent, app)
        page = self.page.inner
        self.var_format = tk.StringVar(value=fr.IMAGE_FORMATS["png"][0])
        self.var_quality = tk.StringVar(value=fr.JPG_QUALITIES[0][0])
        self.var_interval = tk.StringVar(value="5")

        self._build_format_card(page)
        self._build_single_card(page)
        self._build_interval_card(page)
        TaskPanel(page, app.tasks, kinds={fr.KIND_FRAME, fr.KIND_FRAMES}, title="Extrações", height=200).pack(
            fill="x", pady=(0, 10))
        self._restore_settings()
        self._on_format_change()
        self._set_enabled(False)

    # ================================================================== construção
    def _build_format_card(self, page: tk.Misc) -> None:
        card = Card(page, title="2 · Formato da imagem e destino")
        card.pack(fill="x", pady=(0, 14))
        row = PropertyRow(card.body, "Formato", "PNG não perde qualidade (arquivos maiores). JPG gera arquivos "
                          "bem menores com perda quase invisível.", label_width=140)
        row.pack(fill="x", pady=4)
        self.cb_format = ttk.Combobox(row.body, textvariable=self.var_format, state="readonly", width=24,
                                      values=[label for label, _ in fr.IMAGE_FORMATS.values()])
        self.cb_format.pack(side="left")
        self.cb_format.bind("<<ComboboxSelected>>", lambda e: self._on_format_change())
        self.quality_row = PropertyRow(card.body, "Qualidade do JPG", "Quanto melhor a qualidade, maior o arquivo.",
                                       label_width=140)
        self.quality_row.pack(fill="x", pady=4)
        self.cb_quality = ttk.Combobox(self.quality_row.body, textvariable=self.var_quality, state="readonly",
                                       width=24, values=[label for label, _ in fr.JPG_QUALITIES])
        self.cb_quality.pack(side="left")
        tk.Frame(card.body, bg=theme.BORDER, height=1).pack(fill="x", pady=(10, 8))
        self.out = OutputFolderPicker(card.body, default_dir=self.app.config.get("export_dir"),
                                      same_label="Salvar na mesma pasta do vídeo")
        self.out.pack(fill="x")

    def _build_single_card(self, page: tk.Misc) -> None:
        card = Card(page, title="3 · Frame de um instante específico")
        card.pack(fill="x", pady=(0, 14))
        cols = tk.Frame(card.body, bg=theme.PANEL)
        cols.pack(fill="x")
        self.preview = FramePreview(cols, lambda: self.app.ffmpeg_path, width=440, height=250)
        self.preview.pack(side="left", anchor="n")
        side = tk.Frame(cols, bg=theme.PANEL)
        side.pack(side="left", fill="both", expand=True, padx=(18, 0))
        tk.Label(side, text="Instante do vídeo", bg=theme.PANEL, fg=theme.TEXT_DIM, font=theme.fonts(self)["base"],
                 anchor="w").pack(fill="x")
        self.time = TimeField(side, on_change=self._on_time_change, scale_length=200)
        self.time.pack(fill="x", pady=(4, 8))
        steps = tk.Frame(side, bg=theme.PANEL)
        steps.pack(fill="x")
        for text, delta in (("◀ 1 s", -1.0), ("◀ frame", "-f"), ("frame ▶", "+f"), ("1 s ▶", 1.0)):
            b = Button(steps, text, lambda d=delta: self._step(d), style="secondary")
            b.configure(padx=8, pady=4)
            b.pack(side="left", padx=(0, 6))
        self.steps = steps
        self.time_info = tk.Label(side, text="", bg=theme.PANEL, fg=theme.TEXT_FAINT, font=theme.fonts(self)["small"],
                                  anchor="w", justify="left", wraplength=260)
        self.time_info.pack(fill="x", pady=(8, 0))
        self.extract_btn = Button(side, "Extrair este frame", self.extract_single, style="primary", icon="play")
        self.extract_btn.pack(anchor="w", pady=(14, 0))

    def _build_interval_card(self, page: tk.Misc) -> None:
        card = Card(page, title="4 · Vários frames em intervalos")
        card.pack(fill="x", pady=(0, 14))
        row = PropertyRow(card.body, "Salvar um frame a cada", "Exemplo: com 5 segundos, um vídeo de 1 minuto "
                          "gera 12 imagens. Elas são salvas juntas numa nova pasta.", label_width=210)
        row.pack(fill="x", pady=4)
        self.ent_interval = ttk.Entry(row.body, textvariable=self.var_interval, width=8, justify="center")
        self.ent_interval.pack(side="left")
        tk.Label(row.body, text="segundos", bg=theme.PANEL, fg=theme.TEXT_DIM, font=theme.fonts(self)["base"]).pack(
            side="left", padx=8)
        self.estimate_lbl = tk.Label(row.body, text="", bg=theme.PANEL, fg=theme.ACCENT, font=theme.fonts(self)["bold"])
        self.estimate_lbl.pack(side="left", padx=12)
        self.ent_interval.bind("<KeyRelease>", lambda e: self._update_estimate())
        self.interval_btn = Button(card.body, "Extrair frames em intervalos", self.extract_interval, style="primary",
                                   icon="play")
        self.interval_btn.pack(anchor="w", pady=(10, 0))

    # ================================================================== estado
    def on_video_loaded(self, info: MediaInfo) -> None:
        self._set_enabled(True)
        self.time.set_duration(info.duration or 0)
        self.time.set(0.0, notify=False)
        self.preview.show(info, 0.0, delay_ms=0)
        self._update_time_info()
        self._update_estimate()

    def on_video_cleared(self) -> None:
        self._set_enabled(False)
        self.preview.clear()
        self.estimate_lbl.configure(text="")
        self.time_info.configure(text="")

    def _set_enabled(self, enabled: bool) -> None:
        self.time.set_enabled(enabled)
        for child in self.steps.winfo_children():
            child.set_enabled(enabled)
        self.extract_btn.set_enabled(enabled)
        self.interval_btn.set_enabled(enabled)

    def _on_format_change(self) -> None:
        jpg = self._format_id() == "jpg"
        self.cb_quality.configure(state="readonly" if jpg else "disabled")

    def _format_id(self) -> str:
        return next((fid for fid, (label, _) in fr.IMAGE_FORMATS.items() if label == self.var_format.get()), "png")

    def _quality_value(self) -> int:
        return next((q for label, q in fr.JPG_QUALITIES if label == self.var_quality.get()), 2)

    # ================================================================== tempo e pré-visualização
    def _on_time_change(self, seconds: float) -> None:
        if self.info:
            self.preview.show(self.info, seconds)
            self._update_time_info()

    def _step(self, delta) -> None:
        if not self.info:
            return
        try:
            current = self.time.get()
        except ValidationError:
            current = 0.0
        fps = self.info.video.fps or 25.0
        amount = delta if isinstance(delta, float) else ((1 / fps) if delta == "+f" else -(1 / fps))
        self.time.set(fr.clamp_time(self.info, current + amount))

    def _update_time_info(self) -> None:
        if not self.info:
            return
        try:
            seconds = self.time.get()
        except ValidationError:
            return
        fps = self.info.video.fps
        number = f" · frame nº {int(seconds * fps) + 1}" if fps else ""
        self.time_info.configure(text=f"Posição: {format_duration(seconds)} de {format_duration(self.info.duration)}"
                                      f"{number}")

    # ================================================================== ações
    def extract_single(self) -> None:
        if not self.info or not self.require_tools():
            return
        try:
            seconds = self.time.get()
            job = fr.build_frame_job(self.info, seconds, self._format_id(), self._quality_value(),
                                     self.out.resolve())
        except ValidationError as exc:
            message_dialog(self, "Confira os dados", str(exc), kind="warning")
            return
        self.submit(job)

    def _interval(self) -> float:
        return parse_float(self.var_interval.get(), "Intervalo", fr.MIN_INTERVAL)

    def _update_estimate(self) -> None:
        if not self.info:
            return
        try:
            count = fr.estimate_count(self.info.duration, self._interval())
        except ValidationError:
            self.estimate_lbl.configure(text="")
            return
        word = "imagem" if count == 1 else "imagens"
        self.estimate_lbl.configure(text=f"≈ {count} {word}" if count else "")

    def extract_interval(self) -> None:
        if not self.info or not self.require_tools():
            return
        try:
            interval = self._interval()
            count = fr.estimate_count(self.info.duration, interval) or 0
            if count > fr.MAX_SAFE_FRAMES and not message_dialog(
                    self, "Muitas imagens", f"Com este intervalo serão geradas cerca de {count} imagens, o que pode "
                    "ocupar bastante espaço em disco. Deseja continuar?", kind="question",
                    confirm_text="Continuar", cancel_text="Voltar"):
                return
            job = fr.build_interval_job(self.info, interval, self._format_id(), self._quality_value(),
                                        self.out.resolve())
        except ValidationError as exc:
            message_dialog(self, "Confira os dados", str(exc), kind="warning")
            return
        self.submit(job)

    # ================================================================== Ctrl+S
    def on_save(self) -> bool:
        self.app.config.set_tool_settings(self.tool_name, {
            "format": self.var_format.get(), "quality": self.var_quality.get(), "interval": self.var_interval.get(),
            "outdir": self.out.var_folder.get(), "same_folder": self.out.var_same.get()})
        return True

    def _restore_settings(self) -> None:
        saved = self.app.config.get_tool_settings(self.tool_name)
        if saved.get("format") in self.cb_format.cget("values"):
            self.var_format.set(saved["format"])
        if saved.get("quality") in self.cb_quality.cget("values"):
            self.var_quality.set(saved["quality"])
        if isinstance(saved.get("interval"), str) and saved["interval"]:
            self.var_interval.set(saved["interval"])
        if isinstance(saved.get("outdir"), str) and saved["outdir"]:
            self.out.var_folder.set(saved["outdir"])
        self.out.var_same.set(bool(saved.get("same_folder", False)))
