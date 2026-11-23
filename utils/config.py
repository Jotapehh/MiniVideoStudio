"""Configurações do aplicativo, salvas localmente em config/settings.json."""
from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Any

# Pasta raiz do projeto (…/MiniVideoStudio)
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config" / "settings.json"

MAX_RECENT_FILES = 10
HISTORY_KEYS = ("recent_files", "tasks_completed")

DEFAULTS: dict[str, Any] = {
    "export_dir": str(Path.home() / "Videos" / "MiniVideoStudio"),
    "theme": "dark",
    # "status" = só barra de status; "sound" = + som; "dialog" = + janela de aviso; "none" = nada
    "notifications": "status",
    "max_concurrent": 1,
    "ffmpeg_path": "",    # vazio = usar o do PATH
    "ffprobe_path": "",   # vazio = usar o do PATH
    "recent_files": [],   # [{"path": str, "tool": str, "time": "YYYY-MM-DD HH:MM"}]
    "tasks_completed": 0,
    "shortcuts": {},      # personalizações: {"acao": "<Control-Key-x>"}
    "tool_settings": {},  # últimas opções usadas em cada ferramenta (Ctrl+S)
}


class Config:
    """Acesso seguro (entre threads) às configurações, com valores padrão e gravação atômica."""

    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path else DEFAULT_CONFIG_PATH
        self._lock = threading.RLock()
        self._data: dict[str, Any] = copy.deepcopy(DEFAULTS)
        self.load_warning: str = ""  # preenchido se o arquivo estava corrompido
        self.load()

    # ------------------------------------------------------------------ leitura/escrita
    def load(self) -> None:
        with self._lock:
            if not self.path.exists():
                return
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict):
                    raise ValueError("conteúdo não é um objeto JSON")
            except (OSError, ValueError) as exc:
                # Arquivo ilegível: guarda uma cópia e segue com os padrões.
                backup = self.path.with_suffix(".json.bak")
                try:
                    os.replace(self.path, backup)
                except OSError:
                    pass
                self.load_warning = (
                    f"As configurações estavam corrompidas ({exc}) e foram restauradas ao padrão. "
                    f"Uma cópia foi guardada em {backup.name}."
                )
                return
            # Mescla apenas chaves conhecidas, ignorando lixo.
            for key, default in DEFAULTS.items():
                if key in loaded and isinstance(loaded[key], type(default)):
                    self._data[key] = loaded[key]

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)  # troca atômica: nunca deixa o arquivo pela metade

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            value = self._data.get(key, DEFAULTS.get(key, default))
            return copy.deepcopy(value)

    def set(self, key: str, value: Any, save: bool = True) -> None:
        with self._lock:
            self._data[key] = value
            if save:
                self.save()

    def reset(self) -> None:
        with self._lock:
            self._data = copy.deepcopy(DEFAULTS)
            self.save()

    def reset_settings(self) -> None:
        """Volta as configurações ao padrão, mantendo o histórico (arquivos recentes e contador de tarefas)."""
        with self._lock:
            keep = {key: self._data[key] for key in HISTORY_KEYS}
            self._data = copy.deepcopy(DEFAULTS)
            self._data.update(keep)
            self.save()

    def clear_history(self) -> None:
        with self._lock:
            self._data["recent_files"] = []
            self._data["tasks_completed"] = 0
            self.save()

    # ------------------------------------------------------------------ recursos específicos
    def add_recent_file(self, path: str, tool: str, when: str) -> None:
        """Registra um arquivo gerado (mais recente primeiro, sem duplicatas)."""
        with self._lock:
            items = [r for r in self._data["recent_files"] if r.get("path") != path]
            items.insert(0, {"path": path, "tool": tool, "time": when})
            self._data["recent_files"] = items[:MAX_RECENT_FILES]
            self.save()

    def increment_completed(self) -> int:
        with self._lock:
            self._data["tasks_completed"] += 1
            self.save()
            return self._data["tasks_completed"]

    def get_tool_settings(self, tool: str) -> dict[str, Any]:
        return self.get("tool_settings").get(tool, {})

    def set_tool_settings(self, tool: str, values: dict[str, Any]) -> None:
        with self._lock:
            self._data["tool_settings"][tool] = values
            self.save()
