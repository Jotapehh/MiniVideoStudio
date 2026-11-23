"""Compressão de vídeo: perfis, mapeamento qualidade↔CRF e montagem do comando do FFmpeg."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from core.ffprobe import MediaInfo
from core.task_manager import Job
from utils.file_utils import build_output_path
from utils.validators import ValidationError, parse_bitrate


@dataclass(frozen=True)
class Profile:
    id: str
    label: str
    summary: str
    crf: int
    preset: str
    audio_bitrate: str
    max_height: Optional[int]        # None = manter a resolução original


PROFILES: dict[str, Profile] = {p.id: p for p in [
    Profile("high", "Alta qualidade", "Quase indistinguível do original, com economia moderada de espaço.",
            crf=18, preset="slow", audio_bitrate="192k", max_height=None),
    Profile("balanced", "Equilibrado", "O melhor custo-benefício entre qualidade e tamanho. Recomendado.",
            crf=23, preset="medium", audio_bitrate="128k", max_height=None),
    Profile("small", "Arquivo pequeno", "Máxima economia de espaço; limita a imagem a 720p e aceita perda visível.",
            crf=28, preset="medium", audio_bitrate="96k", max_height=720),
]}
DEFAULT_PROFILE = "balanced"

# (nome do preset, explicação curta) — do mais rápido ao que gera arquivos menores
PRESETS: list[tuple[str, str]] = [
    ("ultrafast", "Muito rápido, arquivos maiores"), ("superfast", "Muito rápido"), ("veryfast", "Rápido"),
    ("faster", "Rápido"), ("fast", "Um pouco rápido"), ("medium", "Equilibrado (padrão)"),
    ("slow", "Lento, arquivos menores"), ("slower", "Muito lento"), ("veryslow", "Extremamente lento"),
]
PRESET_NAMES = [name for name, _ in PRESETS]

CODECS = {"libx264": "H.264 (mais compatível)", "libx265": "H.265 / HEVC (arquivos menores)"}
H265_CRF_OFFSET = 5      # CRF 28 no x265 equivale, em qualidade, a CRF 23 no x264
CRF_BEST, CRF_WORST = 14, 38     # extremos da barra de qualidade (0–100 %)
AUDIO_BITRATES = ["64k", "96k", "128k", "192k", "256k"]


def crf_to_quality(crf: int) -> int:
    """CRF (menor = melhor) → qualidade 0–100 % da barra deslizante."""
    return max(0, min(100, round((CRF_WORST - crf) / (CRF_WORST - CRF_BEST) * 100)))


def quality_to_crf(quality: float) -> int:
    """Qualidade 0–100 % → CRF."""
    return round(CRF_WORST - max(0.0, min(100.0, quality)) / 100 * (CRF_WORST - CRF_BEST))


@dataclass
class CompressOptions:
    codec: str = "libx264"
    crf: int = 23
    preset: str = "medium"
    audio_bitrate: str = "128k"
    max_height: Optional[int] = None
    out_dir: str = ""

    @classmethod
    def from_profile(cls, profile_id: str, **overrides) -> "CompressOptions":
        p = PROFILES[profile_id]
        return cls(crf=p.crf, preset=p.preset, audio_bitrate=p.audio_bitrate, max_height=p.max_height, **overrides)


def validate_options(opts: CompressOptions, info: MediaInfo) -> None:
    if not info.video:
        raise ValidationError(f"“{info.filename}” não tem trilha de vídeo.")
    if opts.codec not in CODECS:
        raise ValidationError("Codec de compressão desconhecido.")
    if not 0 <= opts.crf <= 51:
        raise ValidationError("CRF: use um valor entre 0 e 51.")
    if opts.preset not in PRESET_NAMES:
        raise ValidationError("Preset de codificação desconhecido.")
    try:
        parse_bitrate(opts.audio_bitrate)
    except ValidationError as exc:
        raise ValidationError(f"Bitrate de áudio: {exc}") from None


def effective_audio_bitrate(info: MediaInfo, target: str) -> str:
    """Não infla o áudio: se o original já tem bitrate menor que o alvo, usa algo próximo ao original."""
    source = info.audio.bitrate if info.audio else None
    try:
        wanted = float(target.rstrip("kK")) * 1000 if target.lower().endswith("k") else float(target)
    except ValueError:
        return target
    if source and source < wanted:
        return f"{max(64, math.ceil(source / 32000) * 32)}k"
    return target


def build_args(info: MediaInfo, opts: CompressOptions, output_path: str) -> list[str]:
    crf = opts.crf + (H265_CRF_OFFSET if opts.codec == "libx265" else 0)
    args = ["-y", "-i", info.path, "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "0",
            "-c:v", opts.codec, "-crf", str(min(51, crf)), "-preset", opts.preset, "-pix_fmt", "yuv420p"]
    if opts.codec == "libx265":
        args += ["-tag:v", "hvc1"]                        # compatibilidade com aparelhos Apple
    if opts.max_height:
        # Só reduz: se o vídeo já for menor que o limite, não é ampliado.
        args += ["-vf", f"scale=-2:'min({opts.max_height},ih)'"]
    args += ["-c:a", "aac", "-b:a", effective_audio_bitrate(info, opts.audio_bitrate),
             "-movflags", "+faststart", output_path]
    return args


def output_path_for(input_path: str, opts: CompressOptions) -> str:
    return build_output_path(input_path, opts.out_dir or None, "_comprimido", ".mp4")


def build_job(info: MediaInfo, opts: CompressOptions) -> Job:
    validate_options(opts, info)
    output = output_path_for(info.path, opts)
    return Job(name=info.filename, kind="Compressão", input_path=info.path, output_path=output,
               duration=info.duration, ffmpeg_args=build_args(info, opts, output),
               extra={"compare": True, "crf": opts.crf, "preset": opts.preset, "codec": opts.codec})


def summarize_savings(jobs: list[Job]) -> Optional[tuple[int, int, float]]:
    """(bytes originais, bytes finais, economia %) somando as compressões concluídas, ou None."""
    done = [j for j in jobs if j.extra.get("compare") and j.output_size and j.input_size
            and j.state.value == "done"]
    if not done:
        return None
    original, final = sum(j.input_size for j in done), sum(j.output_size for j in done)
    return original, final, (1 - final / original) * 100
