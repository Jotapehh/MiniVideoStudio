"""Página inicial: apresentação, acesso rápido às ferramentas, arquivos recentes e status."""
from __future__ import annotations

import os
import tkinter as tk
from typing import Optional

from core.task_manager import Job
from ui import theme
from ui.base_view import AppContext, BaseView
from ui.sidebar import SECTIONS
from ui.task_panel import TaskPanel
from ui.theme import ICONS
from ui.widgets import Button, Card, EmptyState, ScrollFrame, message_dialog
from utils.file_utils import format_size, open_in_explorer
from utils.shortcuts import shortcut_text

TOOL_DESCRIPTIONS = {
    "converter": "Converta entre MP4, MKV, AVI, MOV e WebM.",
    "compressor": "Diminua o tamanho com perfis de qualidade.",
    "audio_extractor": "Tire o áudio de um vídeo em MP3, WAV e mais.",
    "frames": "Salve imagens de instantes do vídeo.",
    "analyzer": "Veja codecs, resolução, bitrate e mais.",
    "cutter": "Exporte só o trecho que você quer.",
    "audio_converter": "Converta áudios entre vários formatos.",
}
KIND_ICONS = {"Conversão": "converter", "Compressão": "compressor", "Extração de áudio": "audio_extractor",
              "Conversão de áudio": "audio_converter", "Extração de frame": "frames",
              "Extração de frames": "frames", "Corte": "cutter"}


class _Tile(tk.Frame):
    """Número ou estado em destaque."""

    def __init__(self, parent, label: str):
        super().__init__(parent, bg=theme.PANEL, highlightbackground=theme.BORDER, highlightthickness=1)
        f = theme.fonts(parent)
        tk.Label(self, text=label, bg=theme.PANEL, fg=theme.TEXT_DIM, font=f["small"]).pack(anchor="w", padx=14,
                                                                                           pady=(10, 0))
        self.value = tk.Label(self, text="", bg=theme.PANEL, fg=theme.ACCENT, font=f["big_number"])
        self.value.pack(anchor="w", padx=14, pady=(0, 10))

    def set(self, text: str, color: str = theme.ACCENT) -> None:
        self.value.configure(text=text, fg=color)


class _ToolCard(tk.Frame):
    """Cartão clicável de uma ferramenta."""

    def __init__(self, parent, app: AppContext, key: str, name: str, icon: str):
        super().__init__(parent, bg=theme.PANEL, highlightbackground=theme.BORDER, highlightthickness=1,
                         cursor="hand2")
        f = theme.fonts(parent)
        top = tk.Frame(self, bg=theme.PANEL)
        top.pack(fill="x", padx=14, pady=(12, 0))
        icon_lbl = tk.Label(top, text=ICONS[icon], bg=theme.PANEL, fg=theme.ACCENT, font=(f["icon"][0], 20))
        icon_lbl.pack(side="left")
        chip = tk.Label(top, text=shortcut_text(f"goto_{key}", app.config.get("shortcuts")), bg=theme.FIELD,
                        fg=theme.TEXT_DIM, font=f["small"], padx=6, pady=1)
        chip.pack(side="right")
        name_lbl = tk.Label(self, text=name, bg=theme.PANEL, fg=theme.TEXT, font=f["bold"], anchor="w")
        name_lbl.pack(fill="x", padx=14, pady=(8, 0))
        desc_lbl = tk.Label(self, text=TOOL_DESCRIPTIONS[key], bg=theme.PANEL, fg=theme.TEXT_DIM, font=f["small"],
                            anchor="nw", justify="left", wraplength=190)
        desc_lbl.pack(fill="x", padx=14, pady=(2, 12))
        self._widgets = (self, top, icon_lbl, name_lbl, desc_lbl)
        for w in self._widgets + (chip,):
            w.bind("<Button-1>", lambda e: app.navigate(key))
            w.bind("<Enter>", lambda e: self._paint(theme.HOVER, theme.ACCENT))
            w.bind("<Leave>", lambda e: self._paint(theme.PANEL, theme.BORDER))

    def _paint(self, bg: str, border: str) -> None:
        self.configure(highlightbackground=border)
        for w in self._widgets:
            w.configure(bg=bg)


class HomeView(BaseView):
    key = "home"
    title = "Início"

    def __init__(self, parent: tk.Misc, app: AppContext):
        super().__init__(parent, app)
        self.page = ScrollFrame(self, bg=theme.BG)
        self.page.pack(fill="both", expand=True)
        page = self.page.inner
        f = theme.fonts(self)

        # --- apresentação ---
        hero = Card(page, padding=18)
        hero.pack(fill="x", pady=(0, 14))
        tk.Label(hero.body, text="Bem-vindo ao Mini Video Studio", bg=theme.PANEL, fg=theme.TEXT, font=f["title"],
                 anchor="w").pack(fill="x")
        tk.Label(hero.body, justify="left", anchor="w", bg=theme.PANEL, fg=theme.TEXT_DIM, font=f["base"],
                 wraplength=760,
                 text="Converta, comprima, corte e analise vídeos e áudios em um só lugar. Tudo é processado "
                      "localmente no seu computador com FFmpeg: nenhum arquivo é enviado para a internet.").pack(
            fill="x", pady=(6, 0))
        self.warning = tk.Frame(hero.body, bg=theme.PANEL)
        self.warning_lbl = tk.Label(self.warning, bg=theme.PANEL, fg=theme.WARNING, font=f["bold"], anchor="w")
        self.warning_lbl.pack(side="left")
        Button(self.warning, "Configurar FFmpeg", self._open_ffmpeg_settings, style="secondary").pack(
            side="left", padx=12)

        # --- números ---
        tiles = tk.Frame(page, bg=theme.BG)
        tiles.pack(fill="x", pady=(0, 14))
        self.tiles = {}
        for n, (key, label) in enumerate((("done", "Tarefas concluídas"), ("active", "Em andamento ou na fila"),
                                          ("ffmpeg", "FFmpeg"), ("ffprobe", "FFprobe"))):
            tiles.columnconfigure(n, weight=1, uniform="t")
            tile = _Tile(tiles, label)
            tile.grid(row=0, column=n, sticky="ew", padx=(0 if n == 0 else 8, 0))
            self.tiles[key] = tile

        # --- acesso rápido ---
        tk.Label(page, text="Ferramentas", bg=theme.BG, fg=theme.TEXT, font=f["heading"], anchor="w").pack(
            fill="x", pady=(0, 8))
        grid = tk.Frame(page, bg=theme.BG)
        grid.pack(fill="x", pady=(0, 14))
        tools = [s for s in SECTIONS if s[0] != "home"]
        for n, (key, name, icon) in enumerate(tools):
            grid.columnconfigure(n % 4, weight=1, uniform="g")
            _ToolCard(grid, app, key, name, icon).grid(row=n // 4, column=n % 4, sticky="nsew",
                                                       padx=(0 if n % 4 == 0 else 8, 0), pady=(0, 8))

        # --- arquivos recentes ---
        self.recent_card = Card(page, title="Últimos arquivos processados")
        self.recent_card.pack(fill="x", pady=(0, 14))
        self.clear_btn = Button(self.recent_card.header_actions, "Limpar histórico", self._clear_history,
                                style="ghost")
        self.clear_btn.configure(padx=8, pady=2)
        self.clear_btn.pack()
        self.recent_box = tk.Frame(self.recent_card.body, bg=theme.PANEL)
        self.recent_box.pack(fill="x")

        TaskPanel(page, app.tasks, title="Todas as tarefas", height=170).pack(fill="x", pady=(0, 10))

        self._unsubscribe = app.tasks.subscribe(self._on_task_event)
        self.refresh()

    # ================================================================== atualização
    def on_show(self) -> None:
        self.refresh()

    def on_refresh(self) -> None:
        self.refresh()

    def _on_task_event(self, event: str, job: Job) -> None:
        if not self.winfo_exists():
            return
        self._refresh_counts()
        if event == "finished":
            self.refresh_recent()

    def refresh(self) -> None:
        self._refresh_counts()
        self._refresh_tools()
        self.refresh_recent()

    def _refresh_counts(self) -> None:
        self.tiles["done"].set(str(self.app.config.get("tasks_completed")))
        self.tiles["active"].set(str(self.app.tasks.active_count))

    def _refresh_tools(self) -> None:
        for key, status, name in (("ffmpeg", self.app.ffmpeg, "FFmpeg"), ("ffprobe", self.app.ffprobe, "FFprobe")):
            if status.ok:
                self.tiles[key].set(f"✓ {status.version}", theme.SUCCESS)
            else:
                self.tiles[key].set("não encontrado", theme.DANGER)
        if self.app.tools_ok:
            self.warning.pack_forget()
        else:
            self.warning_lbl.configure(text="⚠ O FFmpeg ou o FFprobe não foi encontrado: as ferramentas não "
                                            "funcionarão até você configurá-lo.")
            self.warning.pack(fill="x", pady=(12, 0))

    def refresh_recent(self) -> None:
        for child in self.recent_box.winfo_children():
            child.destroy()
        items = self.app.config.get("recent_files")
        self.clear_btn.set_enabled(bool(items))
        if not items:
            EmptyState(self.recent_box, "folder", "Nada processado ainda",
                       "Os arquivos gerados pelas ferramentas aparecem aqui para você abri-los rapidamente.").pack()
            return
        f = theme.fonts(self)
        for item in items:
            path = item.get("path", "")
            exists = os.path.exists(path)
            row = tk.Frame(self.recent_box, bg=theme.PANEL)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=ICONS[KIND_ICONS.get(item.get("tool", ""), "folder")], bg=theme.PANEL,
                     fg=theme.ACCENT if exists else theme.TEXT_FAINT, font=f["icon_small"], width=3).pack(side="left")
            text = tk.Frame(row, bg=theme.PANEL)
            text.pack(side="left", fill="x", expand=True)
            tk.Label(text, text=os.path.basename(path) or path, bg=theme.PANEL,
                     fg=theme.TEXT if exists else theme.TEXT_FAINT, font=f["bold"], anchor="w").pack(fill="x")
            detail = f"{item.get('tool', '')} · {item.get('time', '')}"
            if exists and os.path.isfile(path):
                detail += f" · {format_size(os.path.getsize(path))}"
            elif not exists:
                detail += " · arquivo movido ou apagado"
            tk.Label(text, text=detail, bg=theme.PANEL, fg=theme.TEXT_DIM, font=f["small"], anchor="w").pack(fill="x")
            if exists:
                btn = Button(row, "Abrir pasta", lambda p=path: open_in_explorer(p), style="secondary", icon="folder")
                btn.configure(padx=10, pady=3)
                btn.pack(side="right")

    # ================================================================== ações
    def _clear_history(self) -> None:
        if message_dialog(self, "Limpar histórico", "Remover a lista de arquivos recentes? Os arquivos em si não "
                          "serão apagados.", kind="question", confirm_text="Limpar", cancel_text="Cancelar",
                          danger=True):
            self.app.config.set("recent_files", [])
            self.refresh_recent()

    def _open_ffmpeg_settings(self) -> None:
        self.app.navigate("settings")
        view: Optional[BaseView] = getattr(self.app.root, "current_view", None)
        if view is not None and hasattr(view, "show_tab"):
            view.show_tab("ffmpeg")

    def destroy(self) -> None:
        if getattr(self, "_unsubscribe", None):
            self._unsubscribe()
        super().destroy()
