"""Tela do Compressor de vídeo."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from core import compressor as cp
from core.converter import RESOLUTION_PRESETS
from core.ffmpeg import list_encoders
from core.task_manager import Job
from ui import theme
from ui.base_view import AppContext, BaseView
from ui.file_list import FileListPanel
from ui.task_panel import TaskPanel
from ui.widgets import Button, Card, OutputFolderPicker, PropertyRow, ScrollFrame, message_dialog
from utils.file_utils import format_size, release_path
from utils.validators import ValidationError

KIND = "Compressão"
KEEP = "Manter resolução original"
CUSTOM_PROFILE = "custom"


class _ProfileCards(tk.Frame):
    """Três cartões clicáveis (um por perfil). Sem seleção = 'Personalizado'."""

    def __init__(self, parent, on_select: Callable[[str], None]):
        super().__init__(parent, bg=theme.PANEL)
        f = theme.fonts(parent)
        self._cards: dict[str, tuple[tk.Frame, list[tk.Label]]] = {}
        for n, profile in enumerate(cp.PROFILES.values()):
            self.columnconfigure(n, weight=1, uniform="p")
            card = tk.Frame(self, bg=theme.FIELD, highlightthickness=2, highlightbackground=theme.BORDER, cursor="hand2")
            card.grid(row=0, column=n, sticky="nsew", padx=(0 if n == 0 else 8, 0))
            title = tk.Label(card, text=profile.label, bg=theme.FIELD, fg=theme.TEXT, font=f["bold"], anchor="w")
            title.pack(fill="x", padx=12, pady=(10, 2))
            desc = tk.Label(card, text=profile.summary, bg=theme.FIELD, fg=theme.TEXT_DIM, font=f["small"],
                            wraplength=190, justify="left", anchor="nw")
            desc.pack(fill="both", expand=True, padx=12, pady=(0, 10))
            for w in (card, title, desc):
                w.bind("<Button-1>", lambda e, pid=profile.id: on_select(pid))
            self._cards[profile.id] = (card, [title, desc])

    def select(self, profile_id: str) -> None:
        for pid, (card, labels) in self._cards.items():
            active = pid == profile_id
            card.configure(highlightbackground=theme.ACCENT if active else theme.BORDER,
                           bg=theme.SELECTED if active else theme.FIELD)
            for lbl in labels:
                lbl.configure(bg=theme.SELECTED if active else theme.FIELD)


class CompressorView(BaseView):
    key = "compressor"
    title = "Compressor de vídeo"
    tool_name = "compressor"
    accepts_multiple_files = True

    def __init__(self, parent: tk.Misc, app: AppContext):
        super().__init__(parent, app)
        self._encoders = list_encoders(app.ffmpeg_path) if app.ffmpeg.ok else {}
        self._syncing = False
        self.profile_id = cp.DEFAULT_PROFILE

        self.page = ScrollFrame(self, bg=theme.BG)
        self.page.pack(fill="both", expand=True)
        page = self.page.inner

        self.files = FileListPanel(app, page, title="1 · Vídeos para comprimir", need="video",
                                   on_change=self._update_buttons)
        self.files.pack(fill="x", pady=(0, 14))

        self.var_crf = tk.StringVar()
        self.var_quality = tk.DoubleVar()
        self.var_preset = tk.StringVar()
        self.var_height = tk.StringVar(value=KEEP)
        self.var_codec = tk.StringVar()
        self.var_abit = tk.StringVar()
        self._build_options(page)

        actions = tk.Frame(page, bg=theme.BG)
        actions.pack(fill="x", pady=(0, 6))
        self.start_btn = Button(actions, "Comprimir", self.start, style="primary", icon="play")
        self.start_btn.pack(side="left")
        self.cancel_btn = Button(actions, "Cancelar compressões", self.cancel_all, style="danger", icon="cancel")
        self.cancel_btn.pack(side="left", padx=(10, 0))
        self.hint_lbl = tk.Label(actions, text="", bg=theme.BG, fg=theme.TEXT_DIM, font=theme.fonts(self)["small"])
        self.hint_lbl.pack(side="left", padx=14)
        self.summary_lbl = tk.Label(page, text="", bg=theme.BG, fg=theme.SUCCESS, font=theme.fonts(self)["bold"],
                                    anchor="w")
        self.summary_lbl.pack(fill="x", pady=(0, 8))

        TaskPanel(page, app.tasks, kinds={KIND}, title="Compressões", height=210).pack(fill="x", pady=(0, 10))

        self._restore_settings()
        self._unsubscribe = app.tasks.subscribe(self._on_task_event)
        self._update_buttons()
        self._update_summary()

    # ================================================================== construção
    def _build_options(self, page: tk.Misc) -> None:
        card = Card(page, title="2 · Perfil e qualidade")
        card.pack(fill="x", pady=(0, 14))
        self.cards = _ProfileCards(card.body, self.apply_profile)
        self.cards.pack(fill="x", pady=(0, 14))

        cols = tk.Frame(card.body, bg=theme.PANEL)
        cols.pack(fill="x")
        cols.columnconfigure((0, 1), weight=1, uniform="c")
        left, right = tk.Frame(cols, bg=theme.PANEL), tk.Frame(cols, bg=theme.PANEL)
        left.grid(row=0, column=0, sticky="nw", padx=(0, 20))
        right.grid(row=0, column=1, sticky="nw")

        def row(parent, label, help, width=140):
            r = PropertyRow(parent, label, help, label_width=width)
            r.pack(fill="x", pady=5)
            return r.body

        body = row(left, "Qualidade", "Controle simples: mais para a direita = melhor qualidade e arquivo maior. "
                   "Ele ajusta o CRF automaticamente.")
        self.scale = ttk.Scale(body, from_=0, to=100, orient="horizontal", length=170, variable=self.var_quality,
                               command=self._on_scale)
        self.scale.pack(side="left")
        self.quality_lbl = tk.Label(body, text="", bg=theme.PANEL, fg=theme.ACCENT, font=theme.fonts(self)["bold"],
                                    width=6)
        self.quality_lbl.pack(side="left", padx=(8, 0))
        body = row(left, "CRF", "CRF: controla a qualidade e o tamanho do vídeo. Valores menores geralmente "
                   "produzem maior qualidade e arquivos maiores.")
        self.spin_crf = ttk.Spinbox(body, from_=0, to=51, width=6, textvariable=self.var_crf, command=self._on_crf)
        self.spin_crf.pack(side="left")
        self.spin_crf.bind("<KeyRelease>", lambda e: self._on_crf())
        self.spin_crf.bind("<FocusOut>", lambda e: self._on_crf(normalize=True))
        tk.Label(body, text="0 = melhor · 51 = pior", bg=theme.PANEL, fg=theme.TEXT_FAINT,
                 font=theme.fonts(self)["small"]).pack(side="left", padx=8)
        body = row(left, "Preset", "Preset: controla a velocidade da codificação. Presets mais lentos podem produzir "
                   "arquivos menores com qualidade semelhante, mas levam mais tempo.")
        self.cb_preset = ttk.Combobox(body, textvariable=self.var_preset, state="readonly", width=30,
                                      values=[f"{n} — {d}" for n, d in cp.PRESETS])
        self.cb_preset.pack(anchor="w")
        self.cb_preset.bind("<<ComboboxSelected>>", lambda e: self._mark_custom())

        body = row(right, "Resolução de saída", "Reduzir a resolução diminui bastante o arquivo. O vídeo nunca é "
                   "ampliado: se já for menor que o limite, permanece como está.", 170)
        self.cb_height = ttk.Combobox(body, textvariable=self.var_height, state="readonly", width=28,
                                      values=[KEEP] + [f"Limitar a {label}" for label, _ in RESOLUTION_PRESETS[2:]])
        self.cb_height.pack(anchor="w")
        self.cb_height.bind("<<ComboboxSelected>>", lambda e: self._mark_custom())
        body = row(right, "Codec", "H.264 funciona em qualquer aparelho. H.265 gera arquivos menores com a mesma "
                   "qualidade, mas é mais lento e menos compatível. Para H.265 o CRF é ajustado automaticamente "
                   "para equivaler à mesma qualidade.", 170)
        codecs = [label for cid, label in cp.CODECS.items()
                  if not self._encoders.get("video") or cid in self._encoders["video"]]
        self.cb_codec = ttk.Combobox(body, textvariable=self.var_codec, state="readonly", width=32,
                                     values=codecs or list(cp.CODECS.values()))
        self.cb_codec.pack(anchor="w")
        self.cb_codec.bind("<<ComboboxSelected>>", lambda e: self._mark_custom())
        body = row(right, "Bitrate do áudio", "Qualidade do som no arquivo final. 128k é suficiente para a maioria dos "
                   "vídeos; 64k–96k economiza espaço em gravações de voz.", 170)
        self.cb_abit = ttk.Combobox(body, textvariable=self.var_abit, values=cp.AUDIO_BITRATES, width=10)
        self.cb_abit.pack(anchor="w")
        self.cb_abit.bind("<<ComboboxSelected>>", lambda e: self._mark_custom())

        tk.Frame(card.body, bg=theme.BORDER, height=1).pack(fill="x", pady=(12, 8))
        self.out = OutputFolderPicker(card.body, default_dir=self.app.config.get("export_dir"),
                                      same_label="Salvar na mesma pasta de cada vídeo original")
        self.out.pack(fill="x")
        tk.Label(card.body, text="O resultado é sempre um MP4 com o sufixo “_comprimido”. O original não é alterado.",
                 bg=theme.PANEL, fg=theme.TEXT_FAINT, font=theme.fonts(self)["small"], anchor="w").pack(
            fill="x", pady=(6, 0), padx=(140, 0))

    # ================================================================== perfis e sincronização
    def apply_profile(self, profile_id: str) -> None:
        p = cp.PROFILES[profile_id]
        self.profile_id = profile_id
        self.cards.select(profile_id)
        self._set_crf(p.crf)
        self.var_preset.set(next(f"{n} — {d}" for n, d in cp.PRESETS if n == p.preset))
        self.var_abit.set(p.audio_bitrate)
        self.var_height.set(KEEP if not p.max_height else self._height_label(p.max_height))

    def _mark_custom(self) -> None:
        self.profile_id = CUSTOM_PROFILE
        self.cards.select("")

    def _set_crf(self, crf: int) -> None:
        self._syncing = True
        try:
            self.var_crf.set(str(crf))
            self.var_quality.set(cp.crf_to_quality(crf))
            self.quality_lbl.configure(text=f"{cp.crf_to_quality(crf)}%")
        finally:
            self._syncing = False

    def _on_scale(self, _value=None) -> None:
        if self._syncing:
            return
        crf = cp.quality_to_crf(self.var_quality.get())
        self._syncing = True
        try:
            self.var_crf.set(str(crf))
            self.quality_lbl.configure(text=f"{round(self.var_quality.get())}%")
        finally:
            self._syncing = False
        self._mark_custom()

    def _on_crf(self, normalize: bool = False) -> None:
        if self._syncing:
            return
        try:
            crf = max(0, min(51, int(self.var_crf.get())))
        except ValueError:
            return                                   # o usuário ainda está digitando
        self._set_crf(crf) if normalize else self._sync_scale_only(crf)
        self._mark_custom()

    def _sync_scale_only(self, crf: int) -> None:
        self._syncing = True
        try:
            self.var_quality.set(cp.crf_to_quality(crf))
            self.quality_lbl.configure(text=f"{cp.crf_to_quality(crf)}%")
        finally:
            self._syncing = False

    @staticmethod
    def _height_label(height: int) -> str:
        label = next(l for l, h in RESOLUTION_PRESETS if h == height)
        return f"Limitar a {label}"

    # ================================================================== opções → objeto
    def collect_options(self) -> cp.CompressOptions:
        try:
            crf = int(self.var_crf.get())
        except ValueError:
            raise ValidationError("CRF: digite um número inteiro entre 0 e 51.") from None
        if not 0 <= crf <= 51:
            raise ValidationError("CRF: use um valor entre 0 e 51.")
        codec = next((cid for cid, label in cp.CODECS.items() if label == self.var_codec.get()), "libx264")
        preset = self.var_preset.get().split(" — ")[0] or "medium"
        height = None
        if self.var_height.get() != KEEP:
            height = next(h for l, h in RESOLUTION_PRESETS if f"Limitar a {l}" == self.var_height.get())
        return cp.CompressOptions(codec=codec, crf=crf, preset=preset, audio_bitrate=self.var_abit.get().strip(),
                                  max_height=height, out_dir=self.out.resolve())

    # ================================================================== ações
    def accept_files(self, paths: list[str]) -> bool:
        self.files.add_paths(paths)
        return True

    def start(self) -> None:
        if not self.require_tools():
            return
        items = self.files.valid_items
        if not items:
            message_dialog(self, "Nenhum vídeo", "Adicione pelo menos um vídeo válido para comprimir.", kind="info")
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
                jobs.append(cp.build_job(item.info, opts))
            except ValidationError as exc:
                problems.append(str(exc))
        if problems:
            text = "\n\n".join(problems[:4])
            if not jobs or not message_dialog(self, "Alguns arquivos serão ignorados",
                                              f"{len(problems)} arquivo(s) não podem ser comprimidos:\n\n{text}",
                                              kind="question", confirm_text="Comprimir os demais",
                                              cancel_text="Voltar"):
                for job in jobs:
                    release_path(job.output_path)
                return
        for job in jobs:
            self.app.tasks.add(job)
        self.files.clear()
        self.app.set_status(f"{len(jobs)} compressão(ões) adicionada(s) à fila.")

    def cancel_all(self) -> None:
        active = [j for j in self.app.tasks.jobs if j.kind == KIND and not j.is_finished]
        if active and message_dialog(self, "Cancelar compressões", f"Cancelar {len(active)} compressão(ões) em "
                                     "andamento ou na fila? Os arquivos incompletos serão apagados.",
                                     kind="question", confirm_text="Cancelar compressões", cancel_text="Continuar",
                                     danger=True):
            for job in active:
                self.app.tasks.cancel(job.id)

    def _on_task_event(self, event: str, job: Job) -> None:
        if job.kind != KIND:
            return
        self._update_buttons()
        if event in ("finished", "removed"):
            self._update_summary()

    def _update_buttons(self) -> None:
        if not self.winfo_exists() or not hasattr(self, "summary_lbl"):
            return
        ready = len(self.files.valid_items)
        self.start_btn.set_enabled(ready > 0 and not self.files.busy)
        self.start_btn.configure(text=f"▶  Comprimir {ready} arquivo{'s' if ready != 1 else ''}" if ready
                                 else "▶  Comprimir")
        self.cancel_btn.set_enabled(any(j.kind == KIND and not j.is_finished for j in self.app.tasks.jobs))
        self.hint_lbl.configure(text="Analisando arquivos…" if self.files.busy else "")

    def _update_summary(self) -> None:
        result = cp.summarize_savings([j for j in self.app.tasks.jobs if j.kind == KIND])
        if not result:
            self.summary_lbl.configure(text="")
            return
        original, final, saved = result
        if saved >= 0:
            text = f"Economia total: {format_size(original)} → {format_size(final)}  ({saved:.0f}% menor)"
            color = theme.SUCCESS
        else:
            text = (f"Atenção: o resultado ({format_size(final)}) ficou maior que o original "
                    f"({format_size(original)}). Tente um CRF mais alto ou o perfil “Arquivo pequeno”.")
            color = theme.WARNING
        self.summary_lbl.configure(text=text, fg=color)

    # ================================================================== Ctrl+S
    def _settings_dict(self) -> dict:
        return {"profile": self.profile_id, "crf": self.var_crf.get(), "preset": self.var_preset.get(),
                "height": self.var_height.get(), "codec": self.var_codec.get(), "abit": self.var_abit.get(),
                "outdir": self.out.var_folder.get(), "same_folder": self.out.var_same.get()}

    def on_save(self) -> bool:
        self.app.config.set_tool_settings(self.tool_name, self._settings_dict())
        return True

    def _restore_settings(self) -> None:
        saved = self.app.config.get_tool_settings(self.tool_name)
        self.var_codec.set(next(iter(self.cb_codec.cget("values")), ""))
        self.apply_profile(cp.DEFAULT_PROFILE)
        profile = saved.get("profile")
        if profile in cp.PROFILES:
            self.apply_profile(profile)
        elif profile == CUSTOM_PROFILE:
            self._mark_custom()
        if str(saved.get("crf", "")).isdigit() and 0 <= int(saved["crf"]) <= 51:
            self._set_crf(int(saved["crf"]))
        for name, var, box in (("preset", self.var_preset, self.cb_preset), ("height", self.var_height, self.cb_height),
                               ("codec", self.var_codec, self.cb_codec)):
            if saved.get(name) in box.cget("values"):
                var.set(saved[name])
        if isinstance(saved.get("abit"), str) and saved["abit"]:
            self.var_abit.set(saved["abit"])
        if isinstance(saved.get("outdir"), str) and saved["outdir"]:
            self.out.var_folder.set(saved["outdir"])
        self.out.var_same.set(bool(saved.get("same_folder", False)))

    def destroy(self) -> None:
        if getattr(self, "_unsubscribe", None):
            self._unsubscribe()
        super().destroy()
