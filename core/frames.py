"""Extração de frames: imagem de um instante, pré-visualização e extração em intervalos."""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Optional

from core.ffmpeg import FFmpegError, friendly_error, run_quick
from core.ffprobe import MediaInfo
from core.task_manager import Job, JobContext, JobError
from utils.file_utils import build_output_path, safe_filename, unique_path
from utils.validators import ValidationError, format_time

KIND_FRAME = "Extração de frame"
KIND_FRAMES = "Extração de frames"

IMAGE_FORMATS: dict[str, tuple[str, str]] = {     # id → (rótulo, extensão)
    "png": ("PNG (sem perdas)", ".png"),
    "jpg": ("JPG (arquivo menor)", ".jpg"),
}
# (rótulo, valor de -q:v do FFmpeg: 2 = melhor … 31 = pior)
JPG_QUALITIES: list[tuple[str, int]] = [("Alta (recomendada)", 2), ("Média", 5), ("Baixa (menor arquivo)", 10)]
MAX_SAFE_FRAMES = 2000                 # acima disso a interface pede confirmação
MIN_INTERVAL = 0.1


class FrameError(RuntimeError):
    """Falha ao gerar uma imagem (mensagem pronta para o usuário)."""


def clamp_time(info: MediaInfo, seconds: float) -> float:
    """Mantém o instante dentro do vídeo. O último instante válido é um frame antes do fim."""
    seconds = max(0.0, seconds)
    if info.duration:
        fps = (info.video.fps if info.video and info.video.fps else 25.0)
        seconds = min(seconds, max(0.0, info.duration - 1.0 / fps))
    return seconds


def _seek(seconds: float) -> str:
    return f"{seconds:.3f}"


# ---------------------------------------------------------------- pré-visualização
def render_preview(info: MediaInfo, seconds: float, out_png: str, ffmpeg_path: str = "ffmpeg",
                   max_w: int = 640, max_h: int = 360) -> str:
    """Gera um PNG reduzido do instante (o Tkinter lê PNG nativamente). Bloqueia: use em segundo plano."""
    seconds = clamp_time(info, seconds)
    args = ["-y", "-ss", _seek(seconds), "-i", info.path, "-an", "-frames:v", "1",
            "-vf", f"scale=w={max_w}:h={max_h}:force_original_aspect_ratio=decrease", out_png]
    try:
        result = run_quick(args, ffmpeg_path=ffmpeg_path, timeout=30)
    except FFmpegError as exc:
        raise FrameError(str(exc)) from exc
    if result.returncode != 0 or not Path(out_png).is_file() or Path(out_png).stat().st_size == 0:
        raise FrameError(friendly_error(result.stderr_tail) if result.stderr_tail
                         else "Não foi possível gerar a pré-visualização deste instante.")
    return out_png


# ---------------------------------------------------------------- frame único
def _quality_args(fmt: str, quality: int) -> list[str]:
    return ["-q:v", str(quality)] if fmt == "jpg" else []


def time_stamp(seconds: float) -> str:
    """'00-01-23.500' — seguro para nomes de arquivo."""
    return format_time(seconds).replace(":", "-")


def validate_format(fmt: str) -> None:
    if fmt not in IMAGE_FORMATS:
        raise ValidationError("Formato de imagem desconhecido. Use PNG ou JPG.")


def build_frame_job(info: MediaInfo, seconds: float, fmt: str = "png", quality: int = 2,
                    out_dir: str = "") -> Job:
    validate_format(fmt)
    if not info.video:
        raise ValidationError(f"“{info.filename}” não tem trilha de vídeo.")
    if info.duration and seconds > info.duration:
        raise ValidationError("O instante escolhido passa da duração do vídeo.")
    seconds = clamp_time(info, seconds)
    output = build_output_path(info.path, out_dir or None, f"_{time_stamp(seconds)}", IMAGE_FORMATS[fmt][1])
    args = ["-y", "-ss", _seek(seconds), "-i", info.path, "-an", "-frames:v", "1",
            *_quality_args(fmt, quality), output]
    return Job(name=info.filename, kind=KIND_FRAME, input_path=info.path, output_path=output, ffmpeg_args=args,
               extra={"time": seconds})


# ---------------------------------------------------------------- vários frames, em intervalos
def estimate_count(duration: Optional[float], interval: float) -> Optional[int]:
    """Quantidade de imagens: uma em 0 s, e depois uma a cada intervalo, sempre antes do fim do vídeo."""
    if not duration or interval <= 0:
        return None
    return max(1, int(math.ceil(duration / interval - 1e-9)))


def _safe_stem(path: str) -> str:
    return safe_filename(Path(path).stem).replace("%", "_")


def build_interval_job(info: MediaInfo, interval: float, fmt: str = "png", quality: int = 2,
                       out_dir: str = "") -> Job:
    """Salva um frame a cada ``interval`` segundos numa nova pasta ``<vídeo>_frames``."""
    validate_format(fmt)
    if not info.video:
        raise ValidationError(f"“{info.filename}” não tem trilha de vídeo.")
    if interval < MIN_INTERVAL:
        raise ValidationError(f"O intervalo mínimo é {MIN_INTERVAL:g} segundo.")
    if info.duration and interval > info.duration:
        raise ValidationError("O intervalo é maior que a duração do vídeo: nenhuma imagem seria gerada além da primeira.")
    base = Path(out_dir) if out_dir else Path(info.path).parent
    folder = unique_path(base / f"{_safe_stem(info.path)}_frames")    # reserva o nome da pasta
    ext = IMAGE_FORMATS[fmt][1]
    pattern = os.path.join(folder, f"{_safe_stem(info.path)}_%05d{ext}")
    args = ["-y", "-i", info.path, "-an", "-vf", f"fps=1/{interval:g}", *_quality_args(fmt, quality), pattern]

    def runner(job: Job, ctx: JobContext) -> None:
        os.makedirs(folder, exist_ok=True)
        job.extra["cleanup_dir"] = folder                  # se cancelar ou falhar, a pasta é apagada
        ctx.run_ffmpeg(args, duration=info.duration)
        count = len(list(Path(folder).glob(f"*{ext}")))
        if count == 0:
            raise JobError("Nenhuma imagem foi gerada. Tente um intervalo menor.")
        job.extra["done_message"] = f"{count} imagem(ns) salva(s) na pasta “{Path(folder).name}”"
        job.extra["count"] = count

    return Job(name=info.filename, kind=KIND_FRAMES, input_path=info.path, duration=info.duration,
               runner=runner, extra={"open_path": folder, "interval": interval})
