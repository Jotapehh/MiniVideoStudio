"""Tela do Conversor de vídeo."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from core import converter as cv
from core.ffmpeg import list_encoders
from core.task_manager import Job
from ui import theme
from ui.base_view import AppContext, BaseView
from ui.file_list import FileListPanel
from ui.task_panel import TaskPanel
from ui.widgets import Button, Card, OutputFolderPicker, PropertyRow, ScrollFrame, message_dialog
from utils.file_utils import release_path
from utils.validators import ValidationError, parse_bitrate, parse_float, parse_resolution

KIND = "Conversão"
AUTO = "Automático"
KEEP = "Manter original"
CUSTOM = "Personalizada…"
_NO_BITRATE_AUDIO = {"copy", "none", "flac", "pcm_s16le"}


class ConverterView(BaseView):
    key = "converter"
    title = "Conversor de vídeo"
    tool_name = "converter"
    accepts_multiple_files = True

    def __init__(self, parent: tk.Misc, app: AppContext):
        super().__init__(parent, app)
        self._encoders = list_encoders(app.ffmpeg_path) if app.ffmpeg.ok else {}

        self.page = ScrollFrame(self, bg=theme.BG)
        self.page.pack(fill="both", expand=True)
        page = self.page.inner

        # --- 1. arquivos ---
        self.files = FileListPanel(app, page, title="1 · Vídeos para converter", need="video",
                                   on_change=self._update_buttons)
        self.files.pack(fill="x", pady=(0, 14))

        # --- 2. opções ---
        self.var_container = tk.StringVar()
        self.var_vcodec = tk.StringVar()
        self.var_acodec = tk.StringVar()
        self.var_res = tk.StringVar(value=KEEP)
        self.var_custom_res = tk.StringVar(value="1280x720")
        self.var_fps = tk.StringVar(value=KEEP)
        self.var_vbit = tk.StringVar(value=AUTO)
        self.var_abit = tk.StringVar(value=AUTO)
        self._build_options(page)

        # --- 3. ação ---
        actions = tk.Frame(page, bg=theme.BG)
        actions.pack(fill="x", pady=(0, 14))
        self.start_btn = Button(actions, "Converter", self.start, style="primary", icon="play")
        self.start_btn.pack(side="left")
        self.cancel_btn = Button(actions, "Cancelar conversões", self.cancel_all, style="danger", icon="cancel")
        self.cancel_btn.pack(side="left", padx=(10, 0))
        self.hint_lbl = tk.Label(actions, text="", bg=theme.BG, fg=theme.TEXT_DIM, font=theme.fonts(self)["small"])
        self.hint_lbl.pack(side="left", padx=14)

        # --- 4. tarefas ---
        TaskPanel(page, app.tasks, kinds={KIND}, title="Conversões", height=210).pack(fill="x", pady=(0, 10))

        self._restore_settings()
        self._refresh_codecs()
        self._update_controls()
        self._unsubscribe = app.tasks.subscribe(lambda event, job: self._update_buttons())
        self._update_buttons()

    # ================================================================== construção
    def _combo(self, parent, var, values, width=22, state="readonly", command=None) -> ttk.Combobox:
        box = ttk.Combobox(parent, textvariable=var, values=values, width=width, state=state)
        box.pack(anchor="w")
        if command:
            box.bind("<<ComboboxSelected>>", lambda e: command())
        return box

    def _build_options(self, page: tk.Misc) -> None:
        card = Card(page, title="2 · Opções de conversão")
        card.pack(fill="x", pady=(0, 14))
        cols = tk.Frame(card.body, bg=theme.PANEL)
        cols.pack(fill="x")
        cols.columnconfigure((0, 1), weight=1, uniform="c")
        left = tk.Frame(cols, bg=theme.PANEL)
        right = tk.Frame(cols, bg=theme.PANEL)
        left.grid(row=0, column=0, sticky="nw", padx=(0, 20))
        right.grid(row=0, column=1, sticky="nw")

        def row(parent, label, help):
            r = PropertyRow(parent, label, help, label_width=140)
            r.pack(fill="x", pady=5)
            return r.body

        # coluna esquerda: formato e codecs
        body = row(left, "Formato de saída", "O tipo de arquivo que será gerado. MP4 é o mais compatível; "
                   "MKV aceita quase tudo; WebM é ideal para a web; MOV é comum em produtos Apple; AVI é antigo.")
        self.cb_container = self._combo(body, self.var_container, [c.label for c in cv.CONTAINERS.values()], 18,
                                        command=self._on_container_change)
        body = row(left, "Codec de vídeo", "Como o vídeo é comprimido. Na dúvida, mantenha H.264.")
        self.cb_vcodec = self._combo(body, self.var_vcodec, [], 26, command=self._on_codec_change)
        body = row(left, "Codec de áudio", "Como o som é comprimido. Na dúvida, mantenha a sugestão.")
        self.cb_acodec = self._combo(body, self.var_acodec, [], 26, command=self._on_codec_change)
        self.codec_help = tk.Label(left, text="", bg=theme.PANEL, fg=theme.TEXT_FAINT, font=theme.fonts(self)["small"],
                                   wraplength=330, justify="left", anchor="w")
        self.codec_help.pack(fill="x", pady=(2, 0))

        # coluna direita: resolução, FPS e bitrates
        body = row(right, "Resolução", "Tamanho da imagem. Reduzir diminui o arquivo. Os valores predefinidos "
                   "mantêm a proporção do vídeo; “Personalizada” usa exatamente LARGURAxALTURA.")
        res_values = [KEEP] + [label for label, _ in cv.RESOLUTION_PRESETS] + [CUSTOM]
        self.cb_res = self._combo(body, self.var_res, res_values, 18, command=self._update_controls)
        self.ent_res = ttk.Entry(body, textvariable=self.var_custom_res, width=11)
        body = row(right, "FPS", "Quadros por segundo. Menos FPS gera arquivos menores, mas o movimento fica menos "
                   "fluido. Deixe “Manter original” se não tiver certeza.")
        self.cb_fps = self._combo(body, self.var_fps, [KEEP] + cv.FPS_PRESETS, 18, state="normal")
        body = row(right, "Bitrate de vídeo", "Quantidade de dados por segundo do vídeo. “Automático” usa qualidade "
                   "constante (recomendado). Defina um valor, como 2500k, só se precisar de um tamanho previsível.")
        self.cb_vbit = self._combo(body, self.var_vbit, [AUTO] + cv.VIDEO_BITRATE_PRESETS, 18, state="normal")
        body = row(right, "Bitrate de áudio", "Qualidade do som. 128k é razoável, 192k é muito boa e 320k é a máxima.")
        self.cb_abit = self._combo(body, self.var_abit, [AUTO] + cv.AUDIO_BITRATE_PRESETS, 18, state="normal")

        # destino (largura total)
        tk.Frame(card.body, bg=theme.BORDER, height=1).pack(fill="x", pady=(12, 8))
        self.out = OutputFolderPicker(card.body, default_dir=self.app.config.get("export_dir"),
                                      same_label="Salvar na mesma pasta de cada vídeo original")
        self.out.pack(fill="x")
        self.var_outdir, self.var_same_folder = self.out.var_folder, self.out.var_same

    # ================================================================== lógica de opções
    def _container_id(self) -> str:
        label = self.var_container.get()
        return next((c.id for c in cv.CONTAINERS.values() if c.label == label), "mp4")

    def _codec_id(self, var: tk.StringVar, kind: str) -> str:
        table = cv.VIDEO_CODECS if kind == "video" else cv.AUDIO_CODECS
        return next((c.id for c in table.values() if c.label == var.get()), "")

    def _refresh_codecs(self, keep_choice: bool = True) -> None:
        """Atualiza as listas de codecs para o contêiner atual, mantendo a escolha se ainda for válida."""
        container = self._container_id()
        for kind, var, box in (("video", self.var_vcodec, self.cb_vcodec), ("audio", self.var_acodec, self.cb_acodec)):
            options = cv.codecs_for(container, kind, self._encoders)
            labels = [o.label for o in options]
            box.configure(values=labels)
            if not (keep_choice and var.get() in labels):
                var.set(labels[0] if labels else "")
        self._update_controls()

    def _on_container_change(self) -> None:
        self._refresh_codecs()

    def _on_codec_change(self) -> None:
        self._update_controls()

    def _update_controls(self) -> None:
        """Habilita/desabilita campos conforme as escolhas (ex.: copiar vídeo ignora resolução e FPS)."""
        vcodec, acodec = self._codec_id(self.var_vcodec, "video"), self._codec_id(self.var_acodec, "audio")
        video_copy = vcodec == "copy"
        for widget in (self.cb_res, self.cb_vbit):
            widget.configure(state="disabled" if video_copy else ("readonly" if widget is self.cb_res else "normal"))
        self.cb_fps.configure(state="disabled" if video_copy else "normal")
        self.cb_abit.configure(state="disabled" if acodec in _NO_BITRATE_AUDIO else "normal")
        if self.var_res.get() == CUSTOM and not video_copy:
            self.ent_res.pack(anchor="w", pady=(4, 0))
        else:
            self.ent_res.pack_forget()
        helps = []
        for table, cid in ((cv.VIDEO_CODECS, vcodec), (cv.AUDIO_CODECS, acodec)):
            if cid in table:
                helps.append(table[cid].help)
        self.codec_help.configure(text="\n".join(helps))

    def collect_options(self) -> cv.ConvertOptions:
        """Lê e valida os campos. Levanta ValidationError com mensagem pronta para o usuário."""
        opts = cv.ConvertOptions(container=self._container_id(),
                                 video_codec=self._codec_id(self.var_vcodec, "video"),
                                 audio_codec=self._codec_id(self.var_acodec, "audio"))
        if not opts.video_codec or not opts.audio_codec:
            raise ValidationError("O FFmpeg instalado não oferece codecs para este formato.")
        if opts.video_codec != "copy":
            res = self.var_res.get()
            if res == CUSTOM:
                opts.size = parse_resolution(self.var_custom_res.get())
            elif res != KEEP:
                opts.height = next(h for label, h in cv.RESOLUTION_PRESETS if label == res)
            fps = self.var_fps.get().strip()
            if fps and fps != KEEP:
                opts.fps = parse_float(fps, "FPS", 1, 240)
            vbit = self.var_vbit.get().strip()
            if vbit and vbit != AUTO:
                opts.video_bitrate = parse_bitrate(vbit)
        if opts.audio_codec not in _NO_BITRATE_AUDIO:
            abit = self.var_abit.get().strip()
            if abit and abit != AUTO:
                opts.audio_bitrate = parse_bitrate(abit)
        opts.out_dir = self.out.resolve()
        return opts

    # ================================================================== ações
    def accept_files(self, paths: list[str]) -> bool:
        self.files.add_paths(paths)
        return True

    def start(self) -> None:
        if not self.require_tools():
            return
        items = self.files.valid_items
        if not items:
            message_dialog(self, "Nenhum vídeo", "Adicione pelo menos um vídeo válido para converter.", kind="info")
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
                jobs.append(cv.build_job(item.info, opts))
            except ValidationError as exc:
                problems.append(str(exc))
        if problems:
            text = "\n\n".join(problems[:4]) + (f"\n\n(+ {len(problems) - 4} outros)" if len(problems) > 4 else "")
            if not jobs:
                message_dialog(self, "Não foi possível converter", text, kind="warning")
                return
            if not message_dialog(self, "Alguns arquivos serão ignorados",
                                  f"{len(problems)} arquivo(s) não podem usar estas opções:\n\n{text}",
                                  kind="question", confirm_text="Converter os demais", cancel_text="Voltar"):
                for job in jobs:
                    release_path(job.output_path)         # desistiu: libera os nomes reservados
                return
        for job in jobs:
            self.app.tasks.add(job)
        self.files.clear()
        self.app.set_status(f"{len(jobs)} conversão(ões) adicionada(s) à fila.")

    def cancel_all(self) -> None:
        active = [j for j in self.app.tasks.jobs if j.kind == KIND and not j.is_finished]
        if not active:
            return
        if message_dialog(self, "Cancelar conversões", f"Cancelar {len(active)} conversão(ões) em andamento ou na "
                          "fila? Os arquivos incompletos serão apagados.", kind="question",
                          confirm_text="Cancelar conversões", cancel_text="Continuar", danger=True):
            for job in active:
                self.app.tasks.cancel(job.id)

    def _update_buttons(self) -> None:
        if not self.winfo_exists() or not hasattr(self, "cancel_btn"):
            return                                   # chamado durante a construção da tela
        ready = len(self.files.valid_items)
        self.start_btn.set_enabled(ready > 0 and not self.files.busy)
        self.start_btn.configure(text=f"▶  Converter {ready} arquivo{'s' if ready != 1 else ''}" if ready
                                 else "▶  Converter")
        active = any(j.kind == KIND and not j.is_finished for j in self.app.tasks.jobs)
        self.cancel_btn.set_enabled(active)
        self.hint_lbl.configure(text="Analisando arquivos…" if self.files.busy else "")

    # ================================================================== Ctrl+S: salvar opções
    def _settings_dict(self) -> dict:
        return {"container": self.var_container.get(), "vcodec": self.var_vcodec.get(),
                "acodec": self.var_acodec.get(), "res": self.var_res.get(), "custom_res": self.var_custom_res.get(),
                "fps": self.var_fps.get(), "vbit": self.var_vbit.get(), "abit": self.var_abit.get(),
                "outdir": self.var_outdir.get(), "same_folder": self.var_same_folder.get()}

    def on_save(self) -> bool:
        self.app.config.set_tool_settings(self.tool_name, self._settings_dict())
        return True

    def _restore_settings(self) -> None:
        saved = self.app.config.get_tool_settings(self.tool_name)
        valid_containers = [c.label for c in cv.CONTAINERS.values()]
        self.var_container.set(saved.get("container") if saved.get("container") in valid_containers else "MP4")
        self._refresh_codecs(keep_choice=False)
        for name, var in (("vcodec", self.var_vcodec), ("acodec", self.var_acodec)):
            if saved.get(name) in (self.cb_vcodec if name == "vcodec" else self.cb_acodec).cget("values"):
                var.set(saved[name])
        for name, var in (("res", self.var_res), ("custom_res", self.var_custom_res), ("fps", self.var_fps),
                          ("vbit", self.var_vbit), ("abit", self.var_abit), ("outdir", self.var_outdir)):
            if isinstance(saved.get(name), str) and saved[name]:
                var.set(saved[name])
        self.var_same_folder.set(bool(saved.get("same_folder", False)))

    def destroy(self) -> None:
        if getattr(self, "_unsubscribe", None):
            self._unsubscribe()
        super().destroy()
