"""Lista de arquivos de mídia usada pelas ferramentas (conversor, compressor, extratores...).

Cada arquivo adicionado é analisado com o FFprobe em segundo plano; a lista mostra duração,
resolução e tamanho e marca como inválidos os arquivos que a ferramenta não consegue usar.
"""
from __future__ import annotations

import os
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, ttk
from typing import Callable, Optional

from core.analyzer import one_line_summary
from core.ffprobe import MediaInfo, ProbeError, probe
from ui import theme
from ui.base_view import AppContext
from ui.widgets import Button, Card, EmptyState, run_in_background
from utils.file_utils import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS, format_duration, format_size


@dataclass
class MediaItem:
    path: str
    info: Optional[MediaInfo] = None
    error: str = ""                 # preenchido se não puder ser usado
    probing: bool = True

    @property
    def ok(self) -> bool:
        return self.info is not None and not self.error


def media_filetypes(need: str) -> list[tuple[str, str]]:
    video = " ".join(f"*{e}" for e in VIDEO_EXTENSIONS)
    audio = " ".join(f"*{e}" for e in AUDIO_EXTENSIONS)
    if need == "video":
        return [("Vídeos", video), ("Todos os arquivos", "*.*")]
    if need == "audio":
        return [("Áudios", audio), ("Todos os arquivos", "*.*")]
    return [("Vídeos e áudios", f"{video} {audio}"), ("Vídeos", video), ("Áudios", audio),
            ("Todos os arquivos", "*.*")]


class FileListPanel(Card):
    """need: "video" exige trilha de vídeo; "audio" exige trilha de áudio; "any" aceita qualquer mídia."""

    def __init__(self, app: AppContext, parent, title: str = "Arquivos", need: str = "video",
                 multiple: bool = True, on_change: Optional[Callable[[], None]] = None, rows: int = 6,
                 dialog_types: Optional[str] = None):
        super().__init__(parent, title=title)
        self.app, self.need, self.multiple, self.on_change = app, need, multiple, on_change
        self.dialog_types = dialog_types or need        # quais arquivos o diálogo “Adicionar” mostra
        self.items: list[MediaItem] = []
        f = theme.fonts(self)

        bar = tk.Frame(self.body, bg=theme.PANEL)
        bar.pack(fill="x", pady=(0, 10))
        Button(bar, "Adicionar arquivos…" if multiple else "Escolher arquivo…", self.browse, style="primary",
               icon="open").pack(side="left")
        self.remove_btn = Button(bar, "Remover selecionados", self.remove_selected, style="secondary")
        self.clear_btn = Button(bar, "Limpar lista", self.clear, style="secondary")
        if multiple:
            self.remove_btn.pack(side="left", padx=(8, 0))
            self.clear_btn.pack(side="left", padx=(8, 0))
        self.count_lbl = tk.Label(bar, text="", bg=theme.PANEL, fg=theme.TEXT_DIM, font=f["small"])
        self.count_lbl.pack(side="right")

        holder = tk.Frame(self.body, bg=theme.PANEL)
        holder.pack(fill="both", expand=True)
        columns = ("name", "duration", "resolution", "size", "status")
        self.tree = ttk.Treeview(holder, columns=columns, show="headings", height=rows,
                                 selectmode="extended" if multiple else "browse")
        for col, text, width, anchor in (("name", "Arquivo", 300, "w"), ("duration", "Duração", 80, "e"),
                                         ("resolution", "Resolução", 95, "e"), ("size", "Tamanho", 85, "e"),
                                         ("status", "Situação", 180, "w")):
            self.tree.heading(col, text=text, anchor=anchor)
            self.tree.column(col, width=width, anchor=anchor, stretch=(col in ("name", "status")))
        self.tree.tag_configure("bad", foreground=theme.DANGER)
        self.tree.tag_configure("busy", foreground=theme.TEXT_DIM)
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Delete>", lambda e: self.remove_selected())
        self.tree.bind("<BackSpace>", lambda e: self.remove_selected())

        what = {"video": "vídeos", "audio": "áudios"}.get(need, "arquivos de mídia")
        self.empty = EmptyState(holder, "folder", "Nenhum arquivo selecionado",
                                f"Clique em “Adicionar arquivos…” ou use Ctrl+O para escolher {what}.")
        self._update_view()

    # ------------------------------------------------------------------ API
    @property
    def valid_items(self) -> list[MediaItem]:
        return [i for i in self.items if i.ok]

    @property
    def busy(self) -> bool:
        return any(i.probing for i in self.items)

    def browse(self) -> None:
        paths = filedialog.askopenfilenames(parent=self, title="Escolher arquivos", filetypes=media_filetypes(self.dialog_types))
        if paths:
            self.add_paths(list(paths))

    def add_paths(self, paths: list[str]) -> None:
        if not self.multiple:
            self._clear_items()
            paths = paths[:1]
        known = {os.path.normcase(os.path.abspath(i.path)) for i in self.items}
        added = 0
        for path in paths:
            key = os.path.normcase(os.path.abspath(path))
            if key in known:
                continue
            known.add(key)
            item = MediaItem(path)
            self.items.append(item)
            self._probe(item)
            added += 1
        if added < len(paths) and self.multiple:
            self.app.set_status(f"{len(paths) - added} arquivo(s) já estavam na lista e foram ignorados.")
        self._update_view()

    def remove_selected(self) -> None:
        selected = {int(i) for i in self.tree.selection()}
        if selected:
            self.items = [item for n, item in enumerate(self.items) if n not in selected]
            self._update_view()

    def clear(self) -> None:
        self._clear_items()
        self._update_view()

    # ------------------------------------------------------------------ internos
    def _clear_items(self) -> None:
        for item in self.items:
            item.probing = False          # resultados que ainda chegarem serão descartados
        self.items = []

    def _probe(self, item: MediaItem) -> None:
        ffprobe_path = self.app.ffprobe_path

        def done(info: MediaInfo) -> None:
            if item not in self.items:
                return
            item.info, item.probing = info, False
            if self.need == "video" and not info.has_video:
                item.error = "Sem trilha de vídeo"
            elif self.need == "audio" and not info.has_audio:
                item.error = "Sem trilha de áudio"
            self._update_view()

        def failed(exc: Exception) -> None:
            if item not in self.items:
                return
            item.probing, item.error = False, str(exc) if isinstance(exc, ProbeError) else f"Erro: {exc}"
            self._update_view()

        run_in_background(self, lambda: probe(item.path, ffprobe_path), done, failed)

    def _update_view(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for n, item in enumerate(self.items):
            info = item.info
            if item.probing:
                status, tag = "Analisando…", "busy"
            elif item.error:
                status, tag = item.error, "bad"
            else:
                status, tag = "✓ Pronto", ""
            self.tree.insert("", "end", iid=str(n), tags=(tag,) if tag else (), values=(
                os.path.basename(item.path),
                format_duration(info.duration) if info else "—",
                info.resolution_text if info and info.has_video else "—",
                format_size(info.size) if info else "—",
                status))
        if self.items:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.5, anchor="center")
        total, valid = len(self.items), len(self.valid_items)
        self.count_lbl.configure(text=(f"{valid} de {total} pronto{'s' if valid != 1 else ''}" if total else ""))
        if self.on_change:
            self.on_change()

    def summary(self, item: MediaItem) -> str:
        return one_line_summary(item.info) if item.info else ""
