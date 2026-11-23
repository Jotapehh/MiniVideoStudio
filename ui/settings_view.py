"""Tela de Configurações: Geral, FFmpeg e FFprobe, e Atalhos de teclado."""
from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import filedialog, ttk

from core.ffmpeg import INSTALL_HELP, ToolStatus, list_encoders
from ui import theme
from ui.base_view import AppContext, BaseView
from ui.shortcuts_view import ShortcutsPanel
from ui.widgets import Button, Card, OutputFolderPicker, PropertyRow, ScrollFrame, message_dialog
from utils.file_utils import ensure_dir
from utils.validators import ValidationError, parse_int

NOTIFY_LABELS = {
    "status": "Somente na barra de status",
    "sound": "Barra de status e som",
    "dialog": "Status, som e aviso ao terminar tudo",
    "none": "Nenhuma notificação",
}
MAX_CONCURRENT_LIMIT = 8
FFMPEG_DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/"

# Encoders que as ferramentas usam, para mostrar o que o FFmpeg instalado suporta.
KEY_ENCODERS = [("video", "libx264", "H.264"), ("video", "libx265", "H.265 / HEVC"), ("video", "libvpx-vp9", "VP9"),
                ("video", "libsvtav1", "AV1"), ("audio", "aac", "AAC"), ("audio", "libmp3lame", "MP3"),
                ("audio", "libopus", "Opus"), ("audio", "libvorbis", "Vorbis"), ("audio", "flac", "FLAC")]


class _Tabs(tk.Frame):
    """Cabeçalho de abas com a aba ativa sublinhada (visual dos painéis do editor de referência)."""

    def __init__(self, parent, names: list[tuple[str, str]], on_select):
        super().__init__(parent, bg=theme.BG)
        self._labels: dict[str, tuple[tk.Label, tk.Frame]] = {}
        f = theme.fonts(parent)
        for key, text in names:
            holder = tk.Frame(self, bg=theme.BG, cursor="hand2")
            holder.pack(side="left", padx=(0, 22))
            label = tk.Label(holder, text=text, bg=theme.BG, fg=theme.TEXT_DIM, font=f["bold"], pady=6)
            label.pack()
            underline = tk.Frame(holder, bg=theme.BG, height=2)
            underline.pack(fill="x")
            for w in (holder, label):
                w.bind("<Button-1>", lambda e, k=key: on_select(k))
            self._labels[key] = (label, underline)
        tk.Frame(self, bg=theme.BORDER, height=1).place(relx=0, rely=1.0, relwidth=1, anchor="sw")

    def select(self, key: str) -> None:
        for k, (label, underline) in self._labels.items():
            label.configure(fg=theme.TEXT if k == key else theme.TEXT_DIM)
            underline.configure(bg=theme.ACCENT if k == key else theme.BG)


class SettingsView(BaseView):
    key = "settings"
    title = "Configurações"

    def __init__(self, parent: tk.Misc, app: AppContext):
        super().__init__(parent, app)
        self.tabs = _Tabs(self, [("general", "Geral"), ("ffmpeg", "FFmpeg e FFprobe"),
                                 ("shortcuts", "Atalhos de teclado")], self.show_tab)
        self.tabs.pack(fill="x", pady=(0, 12))
        self.page = ScrollFrame(self, bg=theme.BG)
        self.page.pack(fill="both", expand=True)
        self.panes: dict[str, tk.Frame] = {}
        self.panes["general"] = self._build_general(self.page.inner)
        self.panes["ffmpeg"] = self._build_ffmpeg(self.page.inner)
        self.shortcuts_panel = ShortcutsPanel(self.page.inner, app)
        self.panes["shortcuts"] = self.shortcuts_panel
        self.current_tab = ""
        self.show_tab("general")

    def show_tab(self, key: str) -> None:
        for pane in self.panes.values():
            pane.pack_forget()
        self.panes[key].pack(fill="x")
        self.current_tab = key
        self.tabs.select(key)
        self.page.canvas.yview_moveto(0)
        if key == "ffmpeg":
            self._refresh_ffmpeg()
        elif key == "shortcuts":
            self.shortcuts_panel.refresh()

    # ================================================================== aba Geral
    def _build_general(self, parent: tk.Misc) -> tk.Frame:
        pane = tk.Frame(parent, bg=theme.BG)
        cfg = self.app.config
        self.var_theme = tk.StringVar(value=theme.THEME_LABELS.get(cfg.get("theme"), theme.THEME_LABELS["dark"]))
        self.var_notify = tk.StringVar(value=NOTIFY_LABELS.get(cfg.get("notifications"), NOTIFY_LABELS["status"]))
        self.var_concurrent = tk.StringVar(value=str(cfg.get("max_concurrent")))

        card = Card(pane, title="Exportação")
        card.pack(fill="x", pady=(0, 14))
        self.out = OutputFolderPicker(card.body, default_dir=cfg.get("export_dir"), label_width=200,
                                      allow_same=False)
        self.out.pack(fill="x")
        tk.Label(card.body, text="Pasta usada como destino inicial em todas as ferramentas. Em cada ferramenta você "
                 "ainda pode escolher outra pasta.", bg=theme.PANEL, fg=theme.TEXT_FAINT, font=theme.fonts(self)["small"],
                 wraplength=640, justify="left", anchor="w").pack(fill="x", padx=(200, 0), pady=(6, 0))

        card = Card(pane, title="Aparência e avisos")
        card.pack(fill="x", pady=(0, 14))
        row = PropertyRow(card.body, "Tema visual", "Escolha a cor de destaque da interface. A mudança é aplicada "
                          "ao reiniciar o programa.", label_width=200)
        row.pack(fill="x", pady=5)
        ttk.Combobox(row.body, textvariable=self.var_theme, state="readonly", width=30,
                     values=list(theme.THEME_LABELS.values())).pack(anchor="w")
        row = PropertyRow(card.body, "Notificações", "Como o programa avisa quando uma tarefa termina. Erros "
                          "sempre aparecem na barra de status.", label_width=200)
        row.pack(fill="x", pady=5)
        ttk.Combobox(row.body, textvariable=self.var_notify, state="readonly", width=34,
                     values=list(NOTIFY_LABELS.values())).pack(side="left")
        Button(row.body, "Testar som", self._test_sound, style="secondary").pack(side="left", padx=10)

        card = Card(pane, title="Desempenho")
        card.pack(fill="x", pady=(0, 14))
        row = PropertyRow(card.body, "Tarefas simultâneas", "Quantas tarefas podem rodar ao mesmo tempo. O FFmpeg "
                          "já usa vários núcleos do processador, então 1 costuma ser o mais rápido; aumente se "
                          "tiver muitos arquivos pequenos.", label_width=200)
        row.pack(fill="x", pady=5)
        ttk.Spinbox(row.body, from_=1, to=MAX_CONCURRENT_LIMIT, width=5, textvariable=self.var_concurrent).pack(
            side="left")
        tk.Label(row.body, text=f"de 1 a {MAX_CONCURRENT_LIMIT}", bg=theme.PANEL, fg=theme.TEXT_FAINT,
                 font=theme.fonts(self)["small"]).pack(side="left", padx=10)

        actions = tk.Frame(pane, bg=theme.BG)
        actions.pack(fill="x", pady=(0, 14))
        Button(actions, "Salvar configurações", self.save, style="primary", icon="ok").pack(side="left")
        Button(actions, "Restaurar padrões", self._reset, style="secondary").pack(side="left", padx=(10, 0))
        Button(actions, "Limpar histórico e estatísticas", self._clear_history, style="ghost").pack(side="right")
        return pane

    def _key_for(self, labels: dict[str, str], shown: str, default: str) -> str:
        return next((k for k, label in labels.items() if label == shown), default)

    def save(self) -> bool:
        """Valida e grava a aba Geral. Devolve False (com aviso) se algum valor for inválido."""
        cfg = self.app.config
        try:
            concurrent = parse_int(self.var_concurrent.get(), "Tarefas simultâneas", 1, MAX_CONCURRENT_LIMIT)
            folder = self.out.var_folder.get().strip()
            if not folder:
                raise ValidationError("Escolha a pasta padrão de exportação.")
            try:
                ensure_dir(folder)
            except OSError as exc:
                raise ValidationError(f"Não foi possível usar a pasta de exportação: {exc}") from None
        except ValidationError as exc:
            message_dialog(self, "Confira as configurações", str(exc), kind="warning")
            return False
        new_theme = self._key_for(theme.THEME_LABELS, self.var_theme.get(), "dark")
        cfg.set("export_dir", folder, save=False)
        cfg.set("notifications", self._key_for(NOTIFY_LABELS, self.var_notify.get(), "status"), save=False)
        cfg.set("max_concurrent", concurrent, save=False)
        cfg.set("theme", new_theme)
        self.app.tasks.set_max_concurrent(concurrent)
        self.app.set_status("✓ Configurações salvas.")
        if new_theme != theme.CURRENT_THEME and message_dialog(
                self, "Reiniciar para aplicar", "A nova cor de destaque será aplicada quando o programa for "
                "reiniciado. Reiniciar agora?", kind="question", confirm_text="Reiniciar agora", cancel_text="Depois"):
            self.app.restart()
        return True

    def on_save(self) -> bool:
        return self.save() if self.current_tab == "general" else False

    def _reset(self) -> None:
        if not message_dialog(self, "Restaurar padrões", "Voltar todas as configurações ao padrão? O histórico de "
                              "arquivos e o contador de tarefas são mantidos.", kind="question",
                              confirm_text="Restaurar", cancel_text="Cancelar", danger=True):
            return
        self.app.config.reset_settings()
        self.app.tasks.set_max_concurrent(self.app.config.get("max_concurrent"))
        self.app.rebind_shortcuts()
        self.app.refresh_tools()
        self._reload_general()
        self.shortcuts_panel.refresh()
        self.app.set_status("✓ Configurações restauradas ao padrão.")

    def _reload_general(self) -> None:
        cfg = self.app.config
        self.out.var_folder.set(cfg.get("export_dir"))
        self.var_theme.set(theme.THEME_LABELS.get(cfg.get("theme"), theme.THEME_LABELS["dark"]))
        self.var_notify.set(NOTIFY_LABELS.get(cfg.get("notifications"), NOTIFY_LABELS["status"]))
        self.var_concurrent.set(str(cfg.get("max_concurrent")))

    def _clear_history(self) -> None:
        if message_dialog(self, "Limpar histórico", "Apagar a lista de arquivos recentes e zerar o contador de tarefas "
                          "concluídas? Os arquivos em si não serão apagados.", kind="question",
                          confirm_text="Limpar", cancel_text="Cancelar", danger=True):
            self.app.config.clear_history()
            self.app.set_status("✓ Histórico e estatísticas apagados.")

    def _test_sound(self) -> None:
        play = getattr(self.app.root, "play_notification_sound", None)
        if play:
            play()

    # ================================================================== aba FFmpeg
    def _build_ffmpeg(self, parent: tk.Misc) -> tk.Frame:
        pane = tk.Frame(parent, bg=theme.BG)
        self.tool_widgets: dict[str, dict] = {}
        for name, title in (("ffmpeg", "FFmpeg"), ("ffprobe", "FFprobe")):
            card = Card(pane, title=title)
            card.pack(fill="x", pady=(0, 14))
            widgets: dict = {}
            for key, label in (("state", "Estado"), ("path", "Caminho do executável"), ("origin", "Origem")):
                row = PropertyRow(card.body, label, label_width=200)
                row.pack(fill="x", pady=3)
                lbl = tk.Label(row.body, text="", bg=theme.PANEL, fg=theme.TEXT, font=theme.fonts(self)["base"],
                               anchor="w", justify="left", wraplength=520)
                lbl.pack(side="left", fill="x", expand=True)
                widgets[key] = lbl
            buttons = tk.Frame(card.body, bg=theme.PANEL)
            buttons.pack(fill="x", pady=(10, 0))
            Button(buttons, "Verificar novamente", self._recheck, style="secondary").pack(side="left")
            Button(buttons, "Escolher executável…", lambda n=name: self._choose(n), style="secondary",
                   icon="folder").pack(side="left", padx=8)
            widgets["reset"] = Button(buttons, "Usar o do PATH", lambda n=name: self._use_path(n), style="ghost")
            widgets["reset"].pack(side="left")
            self.tool_widgets[name] = widgets

        self.help_card = Card(pane, title="FFmpeg não encontrado")
        tk.Label(self.help_card.body, text=INSTALL_HELP, bg=theme.PANEL, fg=theme.TEXT_DIM, font=theme.fonts(self)["base"],
                 justify="left", anchor="w", wraplength=700).pack(fill="x")
        Button(self.help_card.body, "Abrir página de download", lambda: webbrowser.open(FFMPEG_DOWNLOAD_URL),
               style="primary").pack(anchor="w", pady=(10, 0))

        self.codec_card = Card(pane, title="Codecs disponíveis neste FFmpeg")
        self.codec_card.pack(fill="x", pady=(0, 14))
        self.codec_box = tk.Frame(self.codec_card.body, bg=theme.PANEL)
        self.codec_box.pack(fill="x")
        return pane

    def _refresh_ffmpeg(self) -> None:
        custom = {"ffmpeg": self.app.config.get("ffmpeg_path"), "ffprobe": self.app.config.get("ffprobe_path")}
        statuses: dict[str, ToolStatus] = {"ffmpeg": self.app.ffmpeg, "ffprobe": self.app.ffprobe}
        for name, status in statuses.items():
            w = self.tool_widgets[name]
            if status.ok:
                w["state"].configure(text=f"● Funcionando (versão {status.version})", fg=theme.SUCCESS)
            else:
                w["state"].configure(text=f"● {status.error or 'Não encontrado'}", fg=theme.DANGER)
            w["path"].configure(text=status.path or "—")
            w["origin"].configure(text="Caminho personalizado" if custom[name] else "PATH do sistema")
            w["reset"].set_enabled(bool(custom[name]))
        if self.app.tools_ok:
            self.help_card.pack_forget()
        else:
            self.help_card.pack(fill="x", pady=(0, 14), before=self.codec_card)
        for child in self.codec_box.winfo_children():
            child.destroy()
        encoders = list_encoders(self.app.ffmpeg_path) if self.app.ffmpeg.ok else {"video": set(), "audio": set()}
        f = theme.fonts(self)
        for n, (kind, encoder, label) in enumerate(KEY_ENCODERS):
            ok = encoder in encoders.get(kind, set())
            self.codec_box.columnconfigure(n % 3, weight=1, uniform="k")
            tk.Label(self.codec_box, text=f"{'✓' if ok else '✕'}  {label}", bg=theme.PANEL, anchor="w",
                     fg=theme.SUCCESS if ok else theme.TEXT_FAINT, font=f["base"]).grid(row=n // 3, column=n % 3,
                                                                                         sticky="w", pady=3)

    def _recheck(self) -> None:
        self.app.refresh_tools()
        self._refresh_ffmpeg()
        self.app.set_status("✓ FFmpeg e FFprobe verificados." if self.app.tools_ok
                            else "FFmpeg ou FFprobe ainda não foi encontrado.")

    def _choose(self, name: str) -> None:
        path = filedialog.askopenfilename(parent=self, title=f"Escolher o executável do {name}",
                                          filetypes=[("Executáveis", "*.exe"), ("Todos os arquivos", "*.*")])
        if not path:
            return
        self.app.config.set(f"{name}_path", path)
        self.app.refresh_tools()
        self._refresh_ffmpeg()
        status = self.app.ffmpeg if name == "ffmpeg" else self.app.ffprobe
        if not status.ok:
            message_dialog(self, "Executável inválido", f"Este arquivo não respondeu como o {name}. "
                           "Escolha o ffmpeg.exe / ffprobe.exe correto.", kind="error")

    def _use_path(self, name: str) -> None:
        self.app.config.set(f"{name}_path", "")
        self._recheck()

    def on_refresh(self) -> None:
        if self.current_tab == "ffmpeg":
            self._refresh_ffmpeg()
        elif self.current_tab == "shortcuts":
            self.shortcuts_panel.refresh()
