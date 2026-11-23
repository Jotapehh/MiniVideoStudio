"""Funções utilitárias para arquivos, caminhos e formatação de valores."""
from __future__ import annotations

import os
import re
import subprocess
import threading
import sys
from pathlib import Path

VIDEO_EXTENSIONS = (".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v", ".mpg", ".mpeg", ".ts", ".3gp")
AUDIO_EXTENSIONS = (".mp3", ".wav", ".flac", ".aac", ".m4a", ".opus", ".ogg", ".wma")

# Caracteres proibidos em nomes de arquivo no Windows.
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def format_size(num_bytes: float | None) -> str:
    """Converte bytes em texto legível (ex.: 12,4 MB)."""
    if num_bytes is None:
        return "—"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            text = f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            return text.replace(".", ",")
        size /= 1024
    return "—"


def format_duration(seconds: float | None) -> str:
    """Converte segundos em H:MM:SS (ou MM:SS quando menor que 1 hora)."""
    if seconds is None or seconds < 0:
        return "—"
    total = int(round(seconds))
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def format_bitrate(bits_per_second: float | None) -> str:
    """Converte bits/s em kbps ou Mbps."""
    if not bits_per_second:
        return "—"
    if bits_per_second >= 1_000_000:
        return f"{bits_per_second / 1_000_000:.2f} Mbps".replace(".", ",")
    return f"{bits_per_second / 1000:.0f} kbps"


def safe_filename(name: str) -> str:
    """Remove caracteres inválidos de um nome de arquivo."""
    cleaned = _INVALID_CHARS.sub("_", name).strip(" .")
    return cleaned or "arquivo"


_reserved: set[str] = set()
_reserved_lock = threading.Lock()


def _path_key(path: str | os.PathLike) -> str:
    return os.path.normcase(os.path.abspath(path))


def unique_path(path: str | os.PathLike, reserve: bool = True) -> str:
    """Devolve um caminho livre, acrescentando ' (2)', ' (3)'... se necessário.

    Além de evitar arquivos que já existem, "reserva" o nome escolhido: dois trabalhos criados em
    sequência (antes de qualquer um gravar no disco) nunca recebem o mesmo arquivo de saída e,
    portanto, nunca se sobrescrevem. A reserva é liberada com ``release_path`` quando o trabalho termina.
    """
    p = Path(path)
    with _reserved_lock:
        candidate, counter = p, 2
        while candidate.exists() or _path_key(candidate) in _reserved:
            candidate = p.with_name(f"{p.stem} ({counter}){p.suffix}")
            counter += 1
        if reserve:
            _reserved.add(_path_key(candidate))
        return str(candidate)


def release_path(path: str | os.PathLike | None) -> None:
    """Libera a reserva de um caminho de saída (chamado quando a tarefa termina ou é descartada)."""
    if path:
        with _reserved_lock:
            _reserved.discard(_path_key(path))


def build_output_path(input_path: str, out_dir: str | None, suffix: str, extension: str) -> str:
    """Monta <pasta>/<nome><sufixo>.<extensão> sem colidir com arquivos existentes.

    Se out_dir estiver vazio, usa a pasta do arquivo de entrada.
    """
    src = Path(input_path)
    folder = Path(out_dir) if out_dir else src.parent
    ext = extension if extension.startswith(".") else f".{extension}"
    return unique_path(folder / f"{safe_filename(src.stem)}{suffix}{ext}")


def ensure_dir(path: str | os.PathLike) -> str:
    """Cria a pasta (e as pais) se não existir e devolve o caminho."""
    Path(path).mkdir(parents=True, exist_ok=True)
    return str(path)


def remove_quietly(path: str | os.PathLike | None) -> None:
    """Apaga um arquivo ignorando erros (usado para limpar saídas parciais)."""
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def file_size(path: str | os.PathLike | None) -> int | None:
    try:
        return Path(path).stat().st_size if path else None
    except OSError:
        return None


def open_in_explorer(path: str) -> None:
    """Abre a pasta do arquivo no Explorer (Windows), selecionando o arquivo quando possível."""
    p = Path(path)
    try:
        if sys.platform == "win32":
            if p.is_file():
                subprocess.Popen(["explorer", "/select,", str(p)])
            else:
                os.startfile(str(p))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p.parent if p.is_file() else p)])
        else:
            subprocess.Popen(["xdg-open", str(p.parent if p.is_file() else p)])
    except OSError:
        pass
