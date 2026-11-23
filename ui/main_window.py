"""Janela principal: sidebar, área de conteúdo, barra de status, atalhos e ciclo de vida das tarefas."""
from __future__ import annotations

import importlib
import importlib.util
import os
import subprocess
import sys
import time
import tkinter as tk
import traceback
import webbrowser
from datetime import datetime
from tkinter import filedialog, ttk
from typing import Optional
from PIL import Image, ImageTk

from core.ffmpeg import INSTALL_HELP, check_tools
from core.task_manager import Job, TaskManager, TaskState
from ui import theme
from ui.base_view import AppContext, BaseView, ErrorView, PlaceholderView
from ui.sidebar import SECTION_SUBTITLES, SECTION_TITLES, Sidebar
from ui.widgets import Dialog, message_dialog
from utils.config import Config
from utils.file_utils import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS
from utils.shortcuts import display_name, effective_shortcuts, sequences_for

# chave da seção → (módulo, classe). Se o módulo ainda não existir, aparece uma tela provisória.
VIEW_CLASSES: dict[str, tuple[str, str]] = {
    "home": ("ui.home", "HomeView"),
    "converter": ("ui.converter_view", "ConverterView"),
    "compressor": ("ui.compressor_view", "CompressorView"),
    "audio_extractor": ("ui.audio_view", "AudioExtractorView"),
    "frames": ("ui.frames_view", "FramesView"),
    "analyzer": ("ui.analyzer_view", "AnalyzerView"),
    "cutter": ("ui.cutter_view", "CutterView"),
    "audio_converter": ("ui.audio_view", "AudioConverterView"),
    "settings": ("ui.settings_view", "SettingsView"),
}

DEFAULT_HINT = "F1 ajuda · Ctrl+O abrir arquivo · Ctrl+1…8 trocar de ferramenta"
FFMPEG_DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/"
_TYPING_CLASSES = {"Entry", "TEntry", "Text", "Spinbox", "TSpinbox"}


class MainWindow(tk.Tk):
    def __init__(self, settings: Config):
        super().__init__()
        # Atenção: não usar o nome "config" — é um método do próprio Tk.
        self.settings = settings
        self.title("MiniVideoStudio")
        self.minsize(1000, 640)
        self._center(1200, 760)
        theme.apply_style(self)
        self._fonts = theme.fonts(self)

        imagem = Image.open("MiniVideoStudio.ico")
        icone = ImageTk.PhotoImage(imagem)
        self.iconphoto(True, icone)

        ffmpeg, ffprobe = check_tools(settings.get("ffmpeg_path"), settings.get("ffprobe_path"))
        self.tasks = TaskManager(max_concurrent=settings.get("max_concurrent"),
                                 ffmpeg_path=ffmpeg.path or "ffmpeg")
        self.app = AppContext(config=settings, tasks=self.tasks, ffmpeg=ffmpeg, ffprobe=ffprobe,
                              navigate=self.navigate, set_status=self.set_status, root=self,
                              refresh_tools=self.refresh_tools, rebind_shortcuts=self.rebind_shortcuts,
                              restart=self.restart)

        self._views: dict[str, BaseView] = {}
        self.current_key: Optional[str] = None
        self._status_job: Optional[str] = None
        self._tick_job: Optional[str] = None
        self._startup_job: Optional[str] = None
        self._closing = False
        self._restart_requested = False
        self._bound_sequences: list[str] = []
        self._last_state_text = ""
        if not settings.path.exists():
            try:
                settings.save()                       # cria config/settings.json já na primeira execução
            except OSError:
                pass

        self._build_layout()
        self._bind_shortcuts()
        self.tasks.subscribe(self._on_task_event)
        self.protocol("WM_DELETE_WINDOW", self._act_quit)

        self.navigate("home")
        self.set_status(DEFAULT_HINT, timeout_ms=0)
        self._tick()
        self._startup_job = self.after(250, self._startup_checks)

    # ================================================================== layout
    def _center(self, w: int, h: int) -> None:
        x = max(0, (self.winfo_screenwidth() - w) // 2)
        y = max(0, (self.winfo_screenheight() - h) // 3)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_layout(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        self.sidebar = Sidebar(self, self.navigate)
        self.sidebar.grid(row=0, column=0, sticky="ns")
        tk.Frame(self, bg=theme.BORDER, width=1).grid(row=0, column=0, sticky="nse")

        content = tk.Frame(self, bg=theme.BG)
        content.grid(row=0, column=1, sticky="nsew")
        content.rowconfigure(1, weight=1)
        content.columnconfigure(0, weight=1)

        header = tk.Frame(content, bg=theme.BG)
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(22, 10))
        self.title_lbl = tk.Label(header, bg=theme.BG, fg=theme.TEXT, font=self._fonts["title"], anchor="w")
        self.title_lbl.pack(anchor="w")
        self.subtitle_lbl = tk.Label(header, bg=theme.BG, fg=theme.TEXT_DIM, font=self._fonts["subtitle"],
                                     anchor="w")
        self.subtitle_lbl.pack(anchor="w", pady=(2, 0))

        self.host = tk.Frame(content, bg=theme.BG)
        self.host.grid(row=1, column=0, sticky="nsew", padx=28, pady=(0, 14))
        self.host.rowconfigure(0, weight=1)
        self.host.columnconfigure(0, weight=1)

        self._build_status_bar()

    def _build_status_bar(self) -> None:
        bar = tk.Frame(self, bg=theme.BG, highlightbackground=theme.BORDER, highlightthickness=0)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        tk.Frame(bar, bg=theme.BORDER, height=1).pack(fill="x", side="top")
        inner = tk.Frame(bar, bg=theme.BG)
        inner.pack(fill="x", padx=14, pady=5)
        small = self._fonts["small"]
        self.state_lbl = tk.Label(inner, text="● Pronto", bg=theme.BG, fg=theme.SUCCESS, font=small, anchor="w")
        self.state_lbl.pack(side="left")
        self.message_lbl = tk.Label(inner, text="", bg=theme.BG, fg=theme.TEXT_DIM, font=small, anchor="w")
        self.message_lbl.pack(side="left", padx=18, fill="x", expand=True)
        self.ffprobe_chip = tk.Label(inner, bg=theme.BG, font=small, cursor="hand2")
        self.ffprobe_chip.pack(side="right", padx=(12, 0))
        self.ffmpeg_chip = tk.Label(inner, bg=theme.BG, font=small, cursor="hand2")
        self.ffmpeg_chip.pack(side="right")
        for chip in (self.ffmpeg_chip, self.ffprobe_chip):
            chip.bind("<Button-1>", lambda e: self._on_chip_click())
        self._update_tool_chips()

    def _update_tool_chips(self) -> None:
        for chip, status, label in ((self.ffmpeg_chip, self.app.ffmpeg, "FFmpeg"),
                                    (self.ffprobe_chip, self.app.ffprobe, "FFprobe")):
            if status.ok:
                chip.configure(text=f"● {label} {status.version}", fg=theme.SUCCESS)
            else:
                chip.configure(text=f"● {label} não encontrado", fg=theme.DANGER)

    def _on_chip_click(self) -> None:
        if not self.app.tools_ok:
            self.show_tools_dialog()

    # ================================================================== status
    def set_status(self, message: str, timeout_ms: int = 6000) -> None:
        """Mostra uma mensagem na barra de status; volta à dica padrão após ``timeout_ms`` (0 = fixa)."""
        self.message_lbl.configure(text=message)
        if self._status_job:
            self.after_cancel(self._status_job)
            self._status_job = None
        if timeout_ms:
            self._status_job = self.after(timeout_ms, lambda: self.set_status(DEFAULT_HINT, 0))

    def _refresh_state_label(self) -> None:
        counts = self.tasks.counts()
        running, waiting = counts["running"], counts["waiting"]
        if running or waiting:
            text = f"● Processando {running} tarefa{'s' if running != 1 else ''}"
            if waiting:
                text += f" · {waiting} na fila"
            color = theme.ACCENT
        else:
            text, color = "● Pronto", theme.SUCCESS
        if text != self._last_state_text:
            self._last_state_text = text
            self.state_lbl.configure(text=text, fg=color)

    def _tick(self) -> None:
        """Ponte entre as threads de trabalho e o Tkinter: roda a cada 100 ms na thread principal."""
        if self._closing:
            return
        self._tick_job = self.after(100, self._tick)   # reagenda primeiro: um erro abaixo não pode parar o ciclo
        self.tasks.pump()
        self._refresh_state_label()

    # ================================================================== tarefas
    def _on_task_event(self, event: str, job: Job) -> None:
        if event != "finished":
            return
        if job.state == TaskState.DONE:
            try:
                self.settings.increment_completed()
                produced = job.output_path or job.extra.get("open_path")
                if produced:
                    self.settings.add_recent_file(produced, job.kind, datetime.now().strftime("%Y-%m-%d %H:%M"))
            except OSError:
                pass                              # falhar ao gravar estatísticas não pode afetar o resultado
            self.set_status(f"✓ “{job.name}” concluído.")
        elif job.state == TaskState.ERROR:
            self.set_status(f"✕ Falha em “{job.name}”: {job.message}", timeout_ms=10000)
        elif job.state == TaskState.CANCELLED:
            self.set_status(f"“{job.name}” cancelado.")
        self._notify(job)

    def _notify(self, job: Job) -> None:
        mode = self.settings.get("notifications")
        if mode == "none" or job.state == TaskState.CANCELLED:
            return
        if mode in ("sound", "dialog"):
            self.play_notification_sound(error=job.state == TaskState.ERROR)
        if mode == "dialog" and self.tasks.active_count == 0:
            # Adiado: abrir um diálogo modal de dentro do pump pararia a atualização do progresso.
            self.after(50, lambda: message_dialog(
                self, "Mini Video Studio", "Todas as tarefas foram finalizadas.", kind="info"))

    def play_notification_sound(self, error: bool = False) -> None:
        if sys.platform == "win32":
            import winsound
            winsound.MessageBeep(winsound.MB_ICONHAND if error else winsound.MB_ICONASTERISK)
        else:
            self.bell()

    # ================================================================== navegação
    def navigate(self, key: str) -> None:
        if key not in VIEW_CLASSES:
            return
        view = self._views.get(key) or self._create_view(key)
        view.tkraise()
        self.current_key = key
        self.sidebar.select(key)
        self.title_lbl.configure(text=view.title or SECTION_TITLES.get(key, ""))
        self.subtitle_lbl.configure(text=view.subtitle or SECTION_SUBTITLES.get(key, ""))
        view.on_show()

    def _create_view(self, key: str) -> BaseView:
        module_name, class_name = VIEW_CLASSES[key]
        title = SECTION_TITLES[key]
        if importlib.util.find_spec(module_name) is None:
            view: BaseView = PlaceholderView(self.host, self.app, key, title)
        else:
            try:
                cls = getattr(importlib.import_module(module_name), class_name)
                view = cls(self.host, self.app)
                view.key = key
            except Exception:                    # uma tela com defeito não derruba o programa
                traceback.print_exc()
                view = ErrorView(self.host, self.app, key, title, traceback.format_exc(limit=1).strip())
        view.grid(row=0, column=0, sticky="nsew")
        self._views[key] = view
        return view

    @property
    def current_view(self) -> BaseView:
        return self._views[self.current_key]  # type: ignore[index]

    # ================================================================== atalhos
    def _bind_shortcuts(self) -> None:
        for shortcut in effective_shortcuts(self.settings.get("shortcuts")):
            for seq in sequences_for(shortcut):
                try:
                    self.bind_all(seq, lambda e, s=shortcut: self._on_shortcut(s.action, s.works_while_typing))
                    self._bound_sequences.append(seq)
                except tk.TclError:
                    print(f"Atalho inválido ignorado: {seq}", file=sys.stderr)

    def rebind_shortcuts(self) -> None:
        """Reaplica os atalhos (chamado depois que o usuário personaliza algum)."""
        for seq in self._bound_sequences:
            self.unbind_all(seq)
        self._bound_sequences = []
        self._bind_shortcuts()

    def _is_typing(self) -> bool:
        """True se o foco está num campo onde o usuário digita texto."""
        try:
            widget = self.focus_get()
        except KeyError:                          # foco em um popup interno do Tk
            return False
        if widget is None:
            return False
        cls = widget.winfo_class()
        if cls == "TCombobox":
            return str(widget.cget("state")) != "readonly"
        return cls in _TYPING_CLASSES

    def _on_shortcut(self, action: str, works_while_typing: bool) -> Optional[str]:
        grab = self.grab_current()
        if grab is not None and grab.winfo_toplevel() is not self:
            return None                           # há um diálogo aberto: ele trata suas próprias teclas
        if not works_while_typing and self._is_typing():
            return None                           # o usuário está digitando: não roubar a tecla
        if action.startswith("goto_"):
            self.navigate(action[len("goto_"):])
        else:
            handler = getattr(self, f"_act_{action}", None)
            if handler:
                handler()
        return "break"

    # --- ações dos atalhos ---
    _FILETYPES = [
        ("Vídeos e áudios", " ".join(f"*{e}" for e in VIDEO_EXTENSIONS + AUDIO_EXTENSIONS)),
        ("Vídeos", " ".join(f"*{e}" for e in VIDEO_EXTENSIONS)),
        ("Áudios", " ".join(f"*{e}" for e in AUDIO_EXTENSIONS)),
        ("Todos os arquivos", "*.*"),
    ]

    def _act_open_file(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Abrir arquivo", filetypes=self._FILETYPES)
        if path:
            self._deliver_files([path])

    def _act_open_files(self) -> None:
        paths = filedialog.askopenfilenames(parent=self, title="Abrir vários arquivos", filetypes=self._FILETYPES)
        if paths:
            self._deliver_files(list(paths))

    def _deliver_files(self, paths: list[str]) -> None:
        """Entrega os arquivos à tela atual; se ela não os usa, abre a ferramenta mais adequada."""
        view = self.current_view
        if (len(paths) == 1 or view.accepts_multiple_files) and view.accept_files(paths):
            return
        target = "analyzer" if len(paths) == 1 else "converter"
        self.navigate(target)
        if not self.current_view.accept_files(paths):
            self.set_status(f"A ferramenta “{self.current_view.title}” ainda não está disponível para receber arquivos.")

    def _act_save_settings(self) -> None:
        if self.current_view.on_save():
            self.set_status("✓ Configurações da ferramenta salvas.")
        else:
            self.set_status("Não há configurações para salvar nesta tela.")

    def _act_refresh(self) -> None:
        self.refresh_tools()
        self.current_view.on_refresh()
        self.set_status("Informações atualizadas.")

    def _act_cancel(self) -> None:
        if self.current_view.on_escape():
            return
        active = self.tasks.active_count
        if active and message_dialog(self, "Cancelar tarefas", f"Cancelar {active} tarefa{'s' if active != 1 else ''} "
                                     "em andamento ou na fila?", kind="question", confirm_text="Cancelar tarefas",
                                     cancel_text="Continuar", danger=True):
            self.tasks.cancel_all()

    def _act_help(self) -> None:
        dlg = Dialog(self, "Ajuda — Mini Video Studio", width=560)
        f = self._fonts
        tk.Label(dlg.body, text="Como usar", bg=theme.PANEL, fg=theme.TEXT, font=f["heading"]).pack(anchor="w")
        tk.Label(dlg.body, justify="left", anchor="w", bg=theme.PANEL, fg=theme.TEXT_DIM, font=f["base"],
                 wraplength=510,
                 text="Escolha uma ferramenta na barra lateral, selecione seus arquivos, ajuste as opções e inicie. "
                      "As tarefas entram numa fila e mostram o progresso real do FFmpeg; você pode cancelá-las a "
                      "qualquer momento. Passe o mouse sobre o “?” ao lado de cada opção para ver uma explicação."
                 ).pack(anchor="w", pady=(4, 12))
        tk.Label(dlg.body, text="Atalhos de teclado", bg=theme.PANEL, fg=theme.TEXT, font=f["heading"]).pack(anchor="w")
        holder = tk.Frame(dlg.body, bg=theme.PANEL)
        holder.pack(fill="x", pady=(6, 0))
        box = tk.Text(holder, height=14, bg=theme.FIELD, fg=theme.TEXT, relief="flat", font=f["base"],
                      highlightthickness=1, highlightbackground=theme.BORDER, padx=10, pady=8, tabs=("300",))
        bar = ttk.Scrollbar(holder, orient="vertical", command=box.yview)
        box.configure(yscrollcommand=bar.set)
        for sc in effective_shortcuts(self.settings.get("shortcuts")):
            box.insert("end", f"{sc.label}\t{display_name(sc.sequence)}\n")
        box.configure(state="disabled")
        bar.pack(side="right", fill="y")
        box.pack(side="left", fill="x", expand=True)
        dlg.add_button("Fechar", True, "primary")
        dlg.show()

    def restart(self) -> None:
        """Fecha (cancelando tarefas, com confirmação) e abre uma nova instância do programa."""
        self._restart_requested = True
        self._act_quit()
        if not self._closing:                          # o usuário desistiu na confirmação
            self._restart_requested = False

    def _spawn_new_instance(self) -> None:
        try:
            subprocess.Popen([sys.executable, os.path.abspath(sys.argv[0]), *sys.argv[1:]])
        except OSError as exc:
            print(f"Não foi possível reiniciar: {exc}", file=sys.stderr)

    def _act_quit(self) -> None:
        if self._closing:
            return
        active = self.tasks.active_count
        if active and not message_dialog(
                self, "Sair do programa", f"Há {active} tarefa{'s' if active != 1 else ''} em andamento ou na fila. "
                "Se você sair agora, elas serão canceladas.", kind="warning", confirm_text="Cancelar e sair",
                cancel_text="Voltar", danger=True):
            return
        self._closing = True
        self.tasks.cancel_all()
        self.set_status("Encerrando processos…", 0)
        self._finish_quit(time.time() + 10)

    def destroy(self) -> None:
        """Cancela os agendamentos pendentes para não restarem callbacks apontando para uma janela morta."""
        self._closing = True
        for job in (self._tick_job, self._startup_job, self._status_job):
            if job:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
        super().destroy()

    def _finish_quit(self, deadline: float) -> None:
        """Espera o FFmpeg encerrar (e apagar arquivos parciais) antes de fechar a janela."""
        self.tasks.pump()
        if self.tasks.active_count == 0 or time.time() > deadline:
            if self._restart_requested:
                self._spawn_new_instance()
            self.destroy()
        else:
            self.after(120, lambda: self._finish_quit(deadline))

    # ================================================================== FFmpeg / FFprobe
    def refresh_tools(self) -> None:
        ffmpeg, ffprobe = check_tools(self.settings.get("ffmpeg_path"), self.settings.get("ffprobe_path"))
        changed = (ffmpeg.path, ffprobe.path) != (self.app.ffmpeg.path, self.app.ffprobe.path)
        self.app.ffmpeg, self.app.ffprobe = ffmpeg, ffprobe
        self.tasks.ffmpeg_path = ffmpeg.path or "ffmpeg"
        self._update_tool_chips()
        if changed:
            self._invalidate_tool_views()

    def _invalidate_tool_views(self) -> None:
        """Ao trocar de FFmpeg, as telas guardadas são recriadas (a lista de codecs pode ser outra)."""
        keep = {"home", "settings", self.current_key}
        for key in [k for k in self._views if k not in keep]:
            self._views.pop(key).destroy()

    def _startup_checks(self) -> None:
        if self.settings.load_warning:
            message_dialog(self, "Configurações restauradas", self.settings.load_warning, kind="warning")
        if not self.app.tools_ok:
            self.show_tools_dialog()

    def show_tools_dialog(self) -> None:
        """Explica como instalar o FFmpeg e permite informar a pasta manualmente."""
        while not self.app.tools_ok:
            missing = [s.name for s in (self.app.ffmpeg, self.app.ffprobe) if not s.ok]
            dlg = Dialog(self, "FFmpeg não encontrado", width=540)
            tk.Label(dlg.body, text=f"Não foi possível encontrar: {', '.join(missing)}", bg=theme.PANEL,
                     fg=theme.WARNING, font=self._fonts["heading"], anchor="w").pack(anchor="w")
            tk.Label(dlg.body, text=INSTALL_HELP, justify="left", anchor="w", bg=theme.PANEL, fg=theme.TEXT_DIM,
                     font=self._fonts["base"], wraplength=490).pack(anchor="w", pady=(10, 0))
            dlg.add_button("Informar a pasta…", "folder", "primary")     # o 1º adicionado fica mais à direita
            dlg.add_button("Abrir página de download", "download")
            dlg.add_button("Continuar sem FFmpeg", "skip")
            choice = dlg.show()
            if choice == "download":
                webbrowser.open(FFMPEG_DOWNLOAD_URL)
                return
            if choice == "folder":
                folder = filedialog.askdirectory(parent=self, title="Selecione a pasta do FFmpeg (ou a pasta bin)")
                if folder:
                    self.settings.set("ffmpeg_path", folder, save=False)
                    self.settings.set("ffprobe_path", folder)
                    self.refresh_tools()
                    if self.app.tools_ok:
                        self.set_status("✓ FFmpeg e FFprobe encontrados.")
                        return
                    message_dialog(self, "Não encontrado", "Não achei o ffmpeg e o ffprobe nessa pasta. "
                                   "Selecione a pasta que contém ffmpeg.exe e ffprobe.exe.", kind="error")
                    continue
            return

    # ================================================================== erros inesperados do Tkinter
    def report_callback_exception(self, exc, val, tb) -> None:
        """Em vez de falhar em silêncio (sem console no Windows), mostra o erro ao usuário."""
        traceback.print_exception(exc, val, tb)
        self.set_status(f"Erro inesperado: {val}", timeout_ms=12000)
        if getattr(self, "_reporting_error", False):
            return
        self._reporting_error = True
        try:
            message_dialog(self, "Erro inesperado", "Algo deu errado. O programa continua funcionando.",
                           kind="error", detail="".join(traceback.format_exception(exc, val, tb))[-1500:])
        finally:
            self._reporting_error = False
