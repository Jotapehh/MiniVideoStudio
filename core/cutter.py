"""Corte de vídeo: rápido (sem recodificar) ou preciso (recodificando)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core import converter as cv
from core.ffprobe import MediaInfo
from core.task_manager import Job
from utils.file_utils import build_output_path
from utils.validators import ValidationError, format_time

KIND = "Corte"
MODE_FAST = "fast"
MODE_PRECISE = "precise"
MIN_CLIP = 0.1          # segundos


@dataclass
class CutOptions:
    start: float = 0.0
    end: float = 0.0
    mode: str = MODE_FAST
    container: str = "mp4"
    out_dir: str = ""

    @property
    def length(self) -> float:
        return self.end - self.start


def default_container(info: MediaInfo) -> str:
    """Mantém o formato do arquivo original quando ele é um dos suportados; senão, MP4."""
    ext = Path(info.path).suffix.lower().lstrip(".")
    return ext if ext in cv.CONTAINERS else "mp4"


def precise_codecs(container: str, encoders: Optional[dict[str, set[str]]] = None) -> tuple[str, str]:
    """Codecs usados ao recodificar: o primeiro disponível (não 'copiar') de cada lista do contêiner."""
    video = [c.id for c in cv.codecs_for(container, "video", encoders) if c.id != "copy"]
    audio = [c.id for c in cv.codecs_for(container, "audio", encoders) if c.id not in ("copy", "none")]
    if not video or not audio:
        raise ValidationError("O FFmpeg instalado não tem codecs para recodificar neste formato. "
                              "Use o corte rápido ou outro formato.")
    return video[0], audio[0]


def validate_options(opts: CutOptions, info: MediaInfo, encoders: Optional[dict[str, set[str]]] = None) -> None:
    if not info.video:
        raise ValidationError(f"“{info.filename}” não tem trilha de vídeo.")
    if opts.container not in cv.CONTAINERS:
        raise ValidationError("Formato de saída desconhecido.")
    if opts.mode not in (MODE_FAST, MODE_PRECISE):
        raise ValidationError("Modo de corte desconhecido.")
    if opts.start < 0:
        raise ValidationError("O tempo inicial não pode ser negativo.")
    if opts.length < MIN_CLIP:
        raise ValidationError("O tempo final precisa ser maior que o inicial (trecho mínimo de 0,1 segundo).")
    if info.duration and opts.end > info.duration + 0.05:
        raise ValidationError(f"O tempo final passa da duração do vídeo ({format_time(info.duration)}).")
    if opts.mode == MODE_FAST:
        # Sem recodificar, o vídeo e o áudio originais precisam caber no formato de saída.
        cv.validate_options(cv.ConvertOptions(container=opts.container, video_codec="copy", audio_codec="copy"), info)
    else:
        precise_codecs(opts.container, encoders)


def build_args(info: MediaInfo, opts: CutOptions, output_path: str,
               encoders: Optional[dict[str, set[str]]] = None) -> list[str]:
    # -ss ANTES do -i: busca rápida. Ao recodificar, o FFmpeg decodifica até o instante exato.
    args = ["-y", "-ss", f"{opts.start:.3f}", "-i", info.path, "-t", f"{opts.length:.3f}",
            "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "0"]
    if opts.mode == MODE_FAST:
        args += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
        if opts.container in ("mp4", "mov"):
            args += ["-movflags", "+faststart"]
    else:
        video, audio = precise_codecs(opts.container, encoders)
        args += cv.encoding_args(cv.ConvertOptions(container=opts.container, video_codec=video, audio_codec=audio))
    args.append(output_path)
    return args


def build_job(info: MediaInfo, opts: CutOptions, encoders: Optional[dict[str, set[str]]] = None) -> Job:
    validate_options(opts, info, encoders)
    output = build_output_path(info.path, opts.out_dir or None, "_corte", f".{opts.container}")
    return Job(name=info.filename, kind=KIND, input_path=info.path, output_path=output, duration=opts.length,
               ffmpeg_args=build_args(info, opts, output, encoders),
               extra={"mode": opts.mode, "start": opts.start, "end": opts.end})
