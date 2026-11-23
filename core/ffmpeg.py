"""Camada de baixo nível para localizar e executar o FFmpeg.

- Localiza e valida os executáveis (PATH ou caminho personalizado).
- Executa o FFmpeg em subprocess (sem shell) lendo o progresso real de
  ``-progress pipe:1``.
- Cancela de forma segura: pede ao FFmpeg que finalize ('q'), depois
  terminate() e, em último caso, kill().
- Traduz mensagens de erro técnicas para português.

Este módulo NÃO importa Tkinter e pode ser usado em qualquer thread.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

IS_WINDOWS = sys.platform == "win32"


def popen_kwargs() -> dict:
    """Argumentos extras do subprocess: no Windows, evita abrir uma janela de console preta."""
    if IS_WINDOWS:
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


# ---------------------------------------------------------------------- localização/verificação
INSTALL_HELP = (
    "O FFmpeg e o FFprobe não foram encontrados neste computador.\n\n"
    "Como resolver:\n"
    "1. Baixe o FFmpeg para Windows em https://www.gyan.dev/ffmpeg/builds/ (versão “release essentials”).\n"
    "2. Extraia a pasta, por exemplo para C:\\ffmpeg.\n"
    "3. Adicione a pasta C:\\ffmpeg\\bin à variável de ambiente PATH do Windows.\n"
    "4. Feche e abra o Mini Video Studio novamente.\n\n"
    "Alternativa: se o FFmpeg já está instalado em outra pasta, informe o caminho dele no próprio programa."
)


@dataclass
class ToolStatus:
    name: str                 # "ffmpeg" ou "ffprobe"
    path: Optional[str]       # caminho completo, se encontrado
    version: Optional[str]    # ex.: "7.1"
    ok: bool
    error: str = ""


def find_tool(name: str, custom_path: str = "") -> Optional[str]:
    """Procura o executável: primeiro o caminho informado pelo usuário, depois o PATH."""
    if custom_path:
        p = Path(custom_path)
        if p.is_dir():  # o usuário apontou para a pasta do FFmpeg (ou diretamente para a pasta bin)
            for folder in (p, p / "bin"):
                for candidate in (folder / f"{name}.exe", folder / name):
                    if candidate.is_file():
                        return str(candidate)
        elif p.is_file():
            return str(p)
    return shutil.which(name)


def check_tool(name: str, custom_path: str = "") -> ToolStatus:
    """Verifica se o executável existe e responde a ``-version``."""
    path = find_tool(name, custom_path)
    if not path:
        return ToolStatus(name, None, None, False, f"{name} não encontrado.")
    try:
        out = subprocess.run(
            [path, "-version"], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=15, **popen_kwargs(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ToolStatus(name, path, None, False, f"Não foi possível executar {path}: {exc}")
    first_line = (out.stdout or "").splitlines()[0] if out.stdout else ""
    match = re.search(r"version\s+(\S+)", first_line)
    if out.returncode != 0 or not match:
        return ToolStatus(name, path, None, False, f"{path} não respondeu como esperado.")
    version = match.group(1)
    if version[:1].isdigit():
        version = version.split("-")[0]            # "6.1.1-3ubuntu5" → "6.1.1"
    return ToolStatus(name, path, version[:14], True)


def check_tools(ffmpeg_path: str = "", ffprobe_path: str = "") -> tuple[ToolStatus, ToolStatus]:
    return check_tool("ffmpeg", ffmpeg_path), check_tool("ffprobe", ffprobe_path)


# ---------------------------------------------------------------------- codecs disponíveis
_encoder_cache: dict[str, dict[str, set[str]]] = {}
_ENCODER_LINE = re.compile(r"^\s*([VAS])[.\w]{5}\s+(\S+)")


def list_encoders(ffmpeg_path: str = "ffmpeg") -> dict[str, set[str]]:
    """Encoders suportados pelo FFmpeg instalado: {'video': {...}, 'audio': {...}}.

    Usado para só oferecer ao usuário codecs que realmente funcionam.
    """
    if ffmpeg_path in _encoder_cache:
        return _encoder_cache[ffmpeg_path]
    result: dict[str, set[str]] = {"video": set(), "audio": set()}
    try:
        out = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-encoders"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20, **popen_kwargs(),
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return result
    started = False
    for line in out.splitlines():
        if line.strip().startswith("------"):
            started = True
            continue
        if not started:
            continue
        m = _ENCODER_LINE.match(line)
        if m and m.group(1) in "VA":
            result["video" if m.group(1) == "V" else "audio"].add(m.group(2))
    _encoder_cache[ffmpeg_path] = result
    return result


def has_encoder(name: str, kind: str = "video", ffmpeg_path: str = "ffmpeg") -> bool:
    return name in list_encoders(ffmpeg_path).get(kind, set())


# ---------------------------------------------------------------------- execução com progresso
class FFmpegError(RuntimeError):
    """Falha ao iniciar o FFmpeg."""


@dataclass
class Progress:
    fraction: Optional[float]    # 0.0–1.0, ou None se a duração for desconhecida
    out_time: float              # segundos já processados
    speed: Optional[float]       # ex.: 2.4 (vezes a velocidade normal)
    fps: Optional[float]
    size_bytes: Optional[int]


@dataclass
class FFmpegResult:
    returncode: int
    cancelled: bool
    stderr_tail: str             # últimas linhas de erro/aviso do FFmpeg

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.cancelled


def _to_float(value: str) -> Optional[float]:
    try:
        return float(value.strip().rstrip("x"))
    except ValueError:
        return None


def _stop_process(proc: subprocess.Popen) -> None:
    """Encerra o FFmpeg em etapas: 'q' (finaliza o arquivo) → terminate → kill."""
    try:
        if proc.stdin:
            proc.stdin.write("q")
            proc.stdin.flush()
    except (OSError, ValueError):
        pass
    try:
        proc.wait(timeout=4)
        return
    except subprocess.TimeoutExpired:
        pass
    proc.terminate()
    try:
        proc.wait(timeout=3)
        return
    except subprocess.TimeoutExpired:
        pass
    proc.kill()
    proc.wait()


def run_ffmpeg(
    args: list[str],
    *,
    ffmpeg_path: str = "ffmpeg",
    duration: Optional[float] = None,
    on_progress: Optional[Callable[[Progress], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> FFmpegResult:
    """Executa o FFmpeg e bloqueia até terminar (chame sempre fora da thread do Tkinter).

    ``args`` são os argumentos DEPOIS do executável (entrada, filtros, saída...).
    ``duration`` (segundos) permite calcular a porcentagem real do progresso.
    ``on_progress`` é chamado a cada atualização, na thread que executou esta função.
    """
    cmd = [ffmpeg_path, "-hide_banner", "-nostats", "-loglevel", "warning", "-progress", "pipe:1", *args]
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1, **popen_kwargs(),
        )
    except OSError as exc:
        raise FFmpegError(f"Não foi possível iniciar o FFmpeg ({ffmpeg_path}): {exc}") from exc

    stderr_lines: deque[str] = deque(maxlen=40)

    def read_stderr() -> None:
        for line in proc.stderr:  # type: ignore[union-attr]
            if line.strip():
                stderr_lines.append(line.rstrip())

    def read_progress() -> None:
        block: dict[str, str] = {}
        for line in proc.stdout:  # type: ignore[union-attr]
            key, sep, value = line.strip().partition("=")
            if not sep:
                continue
            block[key] = value
            if key != "progress":      # "progress=continue|end" fecha cada bloco
                continue
            if on_progress:
                micro = _to_float(block.get("out_time_us", block.get("out_time_ms", "")))
                seconds = max(0.0, micro / 1_000_000) if micro is not None else 0.0
                fraction = min(1.0, seconds / duration) if duration and duration > 0 else None
                size = _to_float(block.get("total_size", ""))
                on_progress(Progress(
                    fraction=fraction, out_time=seconds,
                    speed=_to_float(block.get("speed", "")), fps=_to_float(block.get("fps", "")),
                    size_bytes=int(size) if size is not None else None,
                ))
            block = {}

    readers = [threading.Thread(target=read_stderr, daemon=True),
               threading.Thread(target=read_progress, daemon=True)]
    for t in readers:
        t.start()

    cancelled = False
    try:
        while True:
            try:
                proc.wait(timeout=0.15)
                break
            except subprocess.TimeoutExpired:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    _stop_process(proc)
                    break
    except BaseException:
        # Qualquer falha inesperada: nunca deixar o FFmpeg órfão em segundo plano.
        _stop_process(proc)
        raise
    finally:
        for t in readers:
            t.join(timeout=2)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if stream:
                    stream.close()
            except OSError:
                pass

    return FFmpegResult(proc.returncode, cancelled, "\n".join(stderr_lines))


def run_quick(args: list[str], *, ffmpeg_path: str = "ffmpeg", timeout: float = 60) -> FFmpegResult:
    """Execução síncrona curta (ex.: extrair um único frame para pré-visualização)."""
    cmd = [ffmpeg_path, "-hide_banner", "-loglevel", "error", *args]
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, stdin=subprocess.DEVNULL, **popen_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return FFmpegResult(-1, False, "A operação demorou demais e foi interrompida.")
    except OSError as exc:
        raise FFmpegError(f"Não foi possível iniciar o FFmpeg ({ffmpeg_path}): {exc}") from exc
    return FFmpegResult(out.returncode, False, (out.stderr or "").strip())


# ---------------------------------------------------------------------- mensagens de erro amigáveis
_ERROR_PATTERNS: list[tuple[str, str]] = [
    (r"No such file or directory", "Arquivo ou pasta não encontrado. Verifique se o arquivo ainda existe."),
    (r"Permission denied", "Sem permissão para ler ou gravar. Verifique se o arquivo está aberto em outro programa ou escolha outra pasta."),
    (r"No space left on device", "Não há espaço livre suficiente no disco de destino."),
    (r"Invalid data found when processing input|moov atom not found",
     "O arquivo parece corrompido ou não é um vídeo/áudio válido."),
    (r"Unknown encoder|Encoder .* not found|Unknown decoder",
     "O FFmpeg instalado não possui o codec escolhido. Selecione outro codec."),
    (r"Output file does not contain any stream|does not contain any stream|matches no streams",
     "O arquivo não tem o tipo de mídia necessário (por exemplo, não possui trilha de áudio ou de vídeo)."),
    (r"width not divisible by 2|height not divisible by 2",
     "A resolução precisa ter largura e altura pares."),
    (r"Error while opening encoder|Could not open encoder",
     "Não foi possível iniciar o codec com estas configurações (verifique resolução, FPS e bitrate)."),
    (r"Could not find codec parameters|Invalid argument",
     "O FFmpeg não conseguiu interpretar o arquivo ou as opções escolhidas."),
    (r"Codec .* not supported|not currently supported in container|Could not write header",
     "O formato de saída não suporta o codec escolhido. Troque o contêiner ou o codec."),
    (r"Conversion failed", "A conversão falhou."),
]


def friendly_error(stderr_tail: str) -> str:
    """Traduz a saída de erro do FFmpeg para uma mensagem compreensível."""
    for pattern, message in _ERROR_PATTERNS:
        if re.search(pattern, stderr_tail or "", re.IGNORECASE):
            return message
    lines = [l for l in (stderr_tail or "").splitlines() if l.strip()]
    if lines:
        return f"O FFmpeg reportou um erro: {lines[-1].strip()}"
    return "O FFmpeg terminou com erro, sem detalhes adicionais."


if __name__ == "__main__":  # verificação rápida: python -m core.ffmpeg
    for status in check_tools():
        mark = "OK " if status.ok else "ERRO"
        print(f"[{mark}] {status.name}: {status.path or '-'} {status.version or ''} {status.error}")
