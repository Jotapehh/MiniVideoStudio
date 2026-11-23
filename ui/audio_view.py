"""Telas do Extrator de áudio (vídeo → áudio) e do Conversor de áudio (áudio → áudio).

As duas ferramentas compartilham as mesmas opções de formato e qualidade; só mudam o tipo de
arquivo aceito, os textos e o tipo de tarefa na fila.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from core import audio as au
from core.ffmpeg import list_encoders
from core.task_manager import Job
from ui import theme
from ui.base_view import AppContext, BaseView
from ui.file_list import FileListPanel
from ui.task_panel import TaskPanel
from ui.widgets import Button, Card, OutputFolderPicker, PropertyRow, ScrollFrame, message_dialog
from utils.file_utils import release_path
from utils.validators import ValidationError


class _AudioToolView(BaseView):
    """Base comum. As subclasses definem textos, tipo de arquivo e tipo de tarefa."""

    tool_name = ""
    kind = ""                 # tipo de tarefa na fila
    dialog_types = "audio"    # o que o diálogo “Adicionar” lista: "video", "audio" ou "any"
    list_title = ""
    verb = ""                 # "Extrair" / "Converter"
    noun_plural = ""          # "extrações" / "conversões"
    accepts_multiple_files = True

    def __init__(self, parent: tk.Misc, app: AppContext):
        super().__init__(parent, app)
        self._encoders = list_encoders(app.ffmpeg_path) if app.ffmpeg.ok else {}
        self.formats = au.formats_available(self._encoders) or list(au.AUDIO_FORMATS.values())

        self.page = ScrollFrame(self, bg=theme.BG)
        self.page.pack(fill="both", expand=True)
        page = self.page.inner

        # Os dois exigem uma trilha de áudio; o extrator mostra vídeos e áudios no diálogo de escolha.
        self.files = FileListPanel(app, page, title=f"1 · {self.list_title}", need="audio",
                                   dialog_types=self.dialog_types, on_change=self._update_buttons)
        self.files.pack(fill="x", pady=(0, 14))

        self.var_format = tk.StringVar()
        self.var_quality = tk.StringVar()
        self.var_rate = tk.StringVar(value=au.SAMPLE_RATES[0][0])
        self.var_channels = tk.StringVar(value=au.CHANNELS[0][0])
        self._build_options(page)

        actions = tk.Frame(page, bg=theme.BG)
        actions.pack(fill="x", pady=(0, 14))
        self.start_btn = Button(actions, self.verb, self.start, style="primary", icon="play")
        self.start_btn.pack(side="left")
        self.cancel_btn = Button(actions, f"Cancelar {self.noun_plural}", self.cancel_all, style="danger",
                                 icon="cancel")
        self.cancel_btn.pack(side="left", padx=(10, 0))
        self.hint_lbl = tk.Label(actions, text="", bg=theme.BG, fg=theme.TEXT_DIM, font=theme.fonts(self)["small"])
        self.hint_lbl.pack(side="left", padx=14)

        TaskPanel(page, app.tasks, kinds={self.kind}, title=self.noun_plural.capitalize(), height=210).pack(
            fill="x", pady=(0, 10))

        self._restore_settings()
        self._unsubscribe = app.tasks.subscribe(lambda event, job: self._update_buttons())
        self._update_buttons()

    # ================================================================== construção
    def _build_options(self, page: tk.Misc) -> None:
        card = Card(page, title="2 · Formato e qualidade")
        card.pack(fill="x", pady=(0, 14))
        cols = tk.Frame(card.body, bg=theme.PANEL)
        cols.pack(fill="x")
        cols.columnconfigure((0, 1), weight=1, uniform="c")
        left, right = tk.Frame(cols, bg=theme.PANEL), tk.Frame(cols, bg=theme.PANEL)
        left.grid(row=0, column=0, sticky="nw", padx=(0, 20))
        right.grid(row=0, column=1, sticky="nw")

        def row(parent, label, help, width=150):
            r = PropertyRow(parent, label, help, label_width=width)
            r.pack(fill="x", pady=5)
            return r

        r = row(left, "Formato de saída", "O tipo de arquivo de áudio que será gerado.")
        self.cb_format = ttk.Combobox(r.body, textvariable=self.var_format, state="readonly", width=20,
                                      values=[f.label for f in self.formats])
        self.cb_format.pack(anchor="w")
        self.cb_format.bind("<<ComboboxSelected>>", lambda e: self._on_format_change())
        self.quality_row = row(left, "Qualidade", "")
        self.cb_quality = ttk.Combobox(self.quality_row.body, textvariable=self.var_quality, state="readonly",
                                       width=26)
        self.cb_quality.pack(anchor="w")
        self.quality_help = tk.Label(left, text="", bg=theme.PANEL, fg=theme.TEXT_FAINT, font=theme.fonts(self)["small"],
                                     wraplength=330, justify="left", anchor="w")
        self.quality_help.pack(fill="x", pady=(2, 0))

        r = row(right, "Taxa de amostragem", "Quantas “fotos” do som são tiradas por segundo. Em geral, “Manter "
                "original” é a melhor escolha. 44.100 Hz é o padrão de música e 48.000 Hz o de vídeo.", 175)
        self.cb_rate = ttk.Combobox(r.body, textvariable=self.var_rate, state="readonly", width=26,
                                    values=[label for label, _ in au.SAMPLE_RATES])
        self.cb_rate.pack(anchor="w")
        r = row(right, "Canais", "Estéreo tem dois canais (esquerdo e direito). Mono mistura tudo em um só e "
                "diminui o arquivo, ideal para voz.", 175)
        self.cb_channels = ttk.Combobox(r.body, textvariable=self.var_channels, state="readonly", width=26,
                                        values=[label for label, _ in au.CHANNELS])
        self.cb_channels.pack(anchor="w")

        tk.Frame(card.body, bg=theme.BORDER, height=1).pack(fill="x", pady=(12, 8))
        self.out = OutputFolderPicker(card.body, default_dir=self.app.config.get("export_dir"),
                                      same_label="Salvar na mesma pasta de cada arquivo original")
        self.out.pack(fill="x")
        self.var_format.set(self.formats[0].label)
        self._on_format_change()

    # ================================================================== lógica de opções
    def _format(self) -> au.AudioFormat:
        return next((f for f in self.formats if f.label == self.var_format.get()), self.formats[0])

    def _on_format_change(self) -> None:
        fmt = self._format()
        self.quality_row.set_label(fmt.quality_label)
        self.quality_row.set_help(fmt.quality_help)
        self.quality_help.configure(text=f"{fmt.description}\n{fmt.quality_help}")
        labels = [text for text, _ in fmt.qualities]
        self.cb_quality.configure(values=labels)
        self.var_quality.set(next(text for text, value in fmt.qualities if value == fmt.default_quality))
        # O Opus trabalha sempre em 48 kHz: a escolha de taxa fica desativada.
        if fmt.id == "opus":
            self.var_rate.set(au.SAMPLE_RATES[0][0])
        self.cb_rate.configure(state="disabled" if fmt.id == "opus" else "readonly")

    def collect_options(self) -> au.AudioOptions:
        fmt = self._format()
        quality = next((v for text, v in fmt.qualities if text == self.var_quality.get()), fmt.default_quality)
        rate = next((v for text, v in au.SAMPLE_RATES if text == self.var_rate.get()), None)
        channels = next((v for text, v in au.CHANNELS if text == self.var_channels.get()), None)
        return au.AudioOptions(format=fmt.id, quality=quality, sample_rate=rate, channels=channels,
                               out_dir=self.out.resolve())

    # ================================================================== ações
    def accept_files(self, paths: list[str]) -> bool:
        self.files.add_paths(paths)
        return True

    def start(self) -> None:
        if not self.require_tools():
            return
        items = self.files.valid_items
        if not items:
            message_dialog(self, "Nenhum arquivo", "Adicione pelo menos um arquivo válido.", kind="info")
            return
        try:
            opts = self.collect_options()
        except ValidationError as exc:
            message_dialog(self, "Confira as opções", str(exc), kind="warning")
            return
        jobs: list[Job] = []
        problems: list[str] = []
        for item in items:
            try:
                jobs.append(au.build_job(item.info, opts, self.kind))
            except ValidationError as exc:
                problems.append(str(exc))
        if problems:
            text = "\n\n".join(problems[:4])
            if not jobs or not message_dialog(self, "Alguns arquivos serão ignorados",
                                              f"{len(problems)} arquivo(s) não podem usar estas opções:\n\n{text}",
                                              kind="question", confirm_text="Continuar com os demais",
                                              cancel_text="Voltar"):
                for job in jobs:
                    release_path(job.output_path)
                return
        for job in jobs:
            self.app.tasks.add(job)
        self.files.clear()
        self.app.set_status(f"{len(jobs)} tarefa(s) adicionada(s) à fila.")

    def cancel_all(self) -> None:
        active = [j for j in self.app.tasks.jobs if j.kind == self.kind and not j.is_finished]
        if active and message_dialog(self, f"Cancelar {self.noun_plural}", f"Cancelar {len(active)} tarefa(s) em "
                                     "andamento ou na fila? Os arquivos incompletos serão apagados.",
                                     kind="question", confirm_text="Cancelar tarefas", cancel_text="Continuar",
                                     danger=True):
            for job in active:
                self.app.tasks.cancel(job.id)

    def _update_buttons(self) -> None:
        if not self.winfo_exists() or not hasattr(self, "hint_lbl"):
            return
        ready = len(self.files.valid_items)
        self.start_btn.set_enabled(ready > 0 and not self.files.busy)
        self.start_btn.configure(text=f"▶  {self.verb} {ready} arquivo{'s' if ready != 1 else ''}" if ready
                                 else f"▶  {self.verb}")
        self.cancel_btn.set_enabled(any(j.kind == self.kind and not j.is_finished for j in self.app.tasks.jobs))
        self.hint_lbl.configure(text="Analisando arquivos…" if self.files.busy else "")

    # ================================================================== Ctrl+S
    def on_save(self) -> bool:
        self.app.config.set_tool_settings(self.tool_name, {
            "format": self.var_format.get(), "quality": self.var_quality.get(), "rate": self.var_rate.get(),
            "channels": self.var_channels.get(), "outdir": self.out.var_folder.get(),
            "same_folder": self.out.var_same.get()})
        return True

    def _restore_settings(self) -> None:
        saved = self.app.config.get_tool_settings(self.tool_name)
        if saved.get("format") in self.cb_format.cget("values"):
            self.var_format.set(saved["format"])
            self._on_format_change()
            if saved.get("quality") in self.cb_quality.cget("values"):
                self.var_quality.set(saved["quality"])
        for name, var, box in (("rate", self.var_rate, self.cb_rate), ("channels", self.var_channels, self.cb_channels)):
            if saved.get(name) in box.cget("values"):
                var.set(saved[name])
        if self._format().id == "opus":
            self.var_rate.set(au.SAMPLE_RATES[0][0])
        if isinstance(saved.get("outdir"), str) and saved["outdir"]:
            self.out.var_folder.set(saved["outdir"])
        self.out.var_same.set(bool(saved.get("same_folder", False)))

    def destroy(self) -> None:
        if getattr(self, "_unsubscribe", None):
            self._unsubscribe()
        super().destroy()


class AudioExtractorView(_AudioToolView):
    key = "audio_extractor"
    title = "Extrator de áudio"
    tool_name = "audio_extractor"
    kind = au.KIND_EXTRACT
    list_title = "Vídeos de onde extrair o áudio"
    dialog_types = "any"
    verb = "Extrair áudio"
    noun_plural = "extrações"


class AudioConverterView(_AudioToolView):
    key = "audio_converter"
    title = "Conversor de áudio"
    tool_name = "audio_converter"
    kind = au.KIND_CONVERT
    list_title = "Arquivos de áudio para converter"
    verb = "Converter áudio"
    noun_plural = "conversões de áudio"
