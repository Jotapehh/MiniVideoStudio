"""Classe base das telas (views) e objeto de contexto compartilhado.

Cada ferramenta (conversor, compressor...) é uma subclasse de ``BaseView``.
A janela principal só conversa com as telas por este contrato, então novas
telas podem ser adicionadas sem alterar a janela.
"""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass, field
from typing import Callable

from core.ffmpeg import ToolStatus
from core.task_manager import Job, TaskManager
from ui import theme
from ui.widgets import EmptyState
from utils.config import Config


@dataclass
class AppContext:
    """Tudo que as telas precisam do restante do aplicativo."""
    config: Config
    tasks: TaskManager
    ffmpeg: ToolStatus
    ffprobe: ToolStatus
    navigate: Callable[[str], None]                       # navigate("converter")
    set_status: Callable[..., None]                       # set_status("mensagem", timeout_ms=5000)
    root: tk.Misc
    refresh_tools: Callable[[], None] = field(default=lambda: None)      # reverifica FFmpeg/FFprobe
    rebind_shortcuts: Callable[[], None] = field(default=lambda: None)   # reaplica os atalhos salvos
    restart: Callable[[], None] = field(default=lambda: None)            # reinicia o programa

    @property
    def ffmpeg_path(self) -> str:
        return self.ffmpeg.path or "ffmpeg"

    @property
    def ffprobe_path(self) -> str:
        return self.ffprobe.path or "ffprobe"

    @property
    def tools_ok(self) -> bool:
        return self.ffmpeg.ok and self.ffprobe.ok


class BaseView(tk.Frame):
    """Contrato de uma tela. Sobrescreva apenas o que precisar."""

    key = ""            # chave da seção na sidebar
    title = ""          # título mostrado no cabeçalho
    subtitle = ""       # frase curta sob o título
    accepts_multiple_files = False

    def __init__(self, parent: tk.Misc, app: AppContext):
        super().__init__(parent, bg=theme.BG)
        self.app = app

    # --- ganchos chamados pela janela principal (todos opcionais) ---
    def on_show(self) -> None:
        """Chamado toda vez que a tela fica visível."""

    def accept_files(self, paths: list[str]) -> bool:
        """Ctrl+O / Ctrl+Shift+O: recebe arquivos escolhidos. Devolva False se a tela não os usa."""
        return False

    def on_save(self) -> bool:
        """Ctrl+S: salva as opções da ferramenta. Devolva False se não houver o que salvar."""
        return False

    def on_refresh(self) -> None:
        """F5: atualiza informações da tela."""

    def on_escape(self) -> bool:
        """Esc: devolva True se a tela tratou o evento (ex.: fechou um painel interno)."""
        return False

    # --- utilidades ---
    def submit(self, job: Job) -> Job:
        """Envia uma tarefa para a fila e avisa na barra de status."""
        self.app.tasks.add(job)
        self.app.set_status(f"“{job.name}” adicionado à fila.")
        return job

    def require_tools(self) -> bool:
        """Confere se FFmpeg e FFprobe estão utilizáveis antes de iniciar uma operação."""
        if self.app.tools_ok:
            return True
        from ui.widgets import message_dialog
        from core.ffmpeg import INSTALL_HELP
        message_dialog(self, "FFmpeg não encontrado", INSTALL_HELP, kind="warning")
        return False


# Em que etapa de desenvolvimento cada tela chega (usado só pelo marcador de posição).
_PLANNED_STAGE = {
    "home": 6, "converter": 3, "compressor": 4, "audio_extractor": 4, "frames": 5,
    "analyzer": 3, "cutter": 5, "audio_converter": 4, "settings": 6,
}


class PlaceholderView(BaseView):
    """Tela provisória para ferramentas que ainda não foram implementadas."""

    def __init__(self, parent: tk.Misc, app: AppContext, key: str, title: str, subtitle: str = ""):
        super().__init__(parent, app)
        self.key, self.title, self.subtitle = key, title, subtitle
        stage = _PLANNED_STAGE.get(key, "?")
        box = EmptyState(self, "info", f"{title} — em desenvolvimento",
                         f"Esta ferramenta será entregue na Etapa {stage} do projeto. "
                         "A navegação e os atalhos de teclado já estão ativos.", bg=theme.BG)
        box.place(relx=0.5, rely=0.4, anchor="center")


class ErrorView(BaseView):
    """Mostrada quando uma tela falha ao carregar, sem derrubar o programa inteiro."""

    def __init__(self, parent: tk.Misc, app: AppContext, key: str, title: str, error: str):
        super().__init__(parent, app)
        self.key, self.title = key, title
        box = EmptyState(self, "cancel", "Não foi possível abrir esta tela", error, bg=theme.BG)
        box.place(relx=0.5, rely=0.4, anchor="center")
