"""Extração de áudio de vídeos e conversão entre formatos de áudio (MP3, WAV, AAC, FLAC, OPUS)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.ffprobe import MediaInfo
from core.task_manager import Job
from utils.file_utils import build_output_path
from utils.validators import ValidationError, parse_bitrate

KIND_EXTRACT = "Extração de áudio"
KIND_CONVERT = "Conversão de áudio"


@dataclass(frozen=True)
class AudioFormat:
    id: str
    label: str
    ext: str
    codec: str                                   # encoder do FFmpeg
    quality_label: str                           # nome do controle de qualidade deste formato
    quality_help: str
    qualities: tuple[tuple[str, str], ...]       # (texto exibido, valor interno)
    default_quality: str
    description: str


AUDIO_FORMATS: dict[str, AudioFormat] = {f.id: f for f in [
    AudioFormat("mp3", "MP3", ".mp3", "libmp3lame", "Bitrate",
                "Quanto maior o bitrate, melhor a qualidade e maior o arquivo. 192 kbps já é muito bom; 320 kbps é o máximo.",
                (("128 kbps", "128k"), ("192 kbps (recomendado)", "192k"), ("256 kbps", "256k"), ("320 kbps", "320k")),
                "192k", "O formato mais compatível com qualquer aparelho."),
    AudioFormat("wav", "WAV", ".wav", "pcm_s16le", "Profundidade",
                "16 bits é o padrão de CD. 24 bits é usado em produção de áudio e gera arquivos maiores.",
                (("16 bits (padrão de CD)", "pcm_s16le"), ("24 bits (estúdio)", "pcm_s24le")),
                "pcm_s16le", "Sem compressão e sem perdas, com arquivos grandes."),
    AudioFormat("aac", "AAC (.m4a)", ".m4a", "aac", "Bitrate",
                "Quanto maior o bitrate, melhor a qualidade e maior o arquivo.",
                (("96 kbps", "96k"), ("128 kbps", "128k"), ("192 kbps (recomendado)", "192k"),
                 ("256 kbps", "256k"), ("320 kbps", "320k")),
                "192k", "Qualidade melhor que o MP3 no mesmo tamanho. Salvo como .m4a."),
    AudioFormat("flac", "FLAC", ".flac", "flac", "Nível de compressão",
                "Não altera a qualidade (é sem perdas): níveis maiores só deixam o arquivo um pouco menor e demoram mais.",
                (("0 (mais rápido)", "0"), ("5 (recomendado)", "5"), ("8 (menor arquivo)", "8")),
                "5", "Sem perdas: qualidade idêntica ao original, com arquivos menores que o WAV."),
    AudioFormat("opus", "OPUS", ".opus", "libopus", "Bitrate",
                "O Opus rende muito bem em bitrates baixos: 96–128 kbps já soam excelentes.",
                (("64 kbps", "64k"), ("96 kbps", "96k"), ("128 kbps (recomendado)", "128k"),
                 ("192 kbps", "192k"), ("256 kbps", "256k")),
                "128k", "Moderno e muito eficiente, ótimo para voz e música na web."),
]}

SAMPLE_RATES: list[tuple[str, Optional[int]]] = [
    ("Manter original", None), ("22.050 Hz", 22050), ("44.100 Hz (padrão de CD)", 44100),
    ("48.000 Hz (vídeo)", 48000), ("96.000 Hz", 96000),
]
CHANNELS: list[tuple[str, Optional[int]]] = [("Manter original", None), ("Mono", 1), ("Estéreo", 2)]

_OPUS_RATES = {8000, 12000, 16000, 24000, 48000}
_MP3_MAX_RATE = 48000


@dataclass
class AudioOptions:
    format: str = "mp3"
    quality: str = "192k"                 # bitrate, nível FLAC ou codec PCM, conforme o formato
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    out_dir: str = ""


def formats_available(encoders: Optional[dict[str, set[str]]] = None) -> list[AudioFormat]:
    """Formatos cujo encoder existe no FFmpeg instalado (todos, se a lista de encoders for desconhecida)."""
    available = (encoders or {}).get("audio") or set()
    return [f for f in AUDIO_FORMATS.values() if not available or f.codec in available]


def validate_options(opts: AudioOptions, info: MediaInfo) -> None:
    fmt = AUDIO_FORMATS.get(opts.format)
    if not fmt:
        raise ValidationError("Formato de áudio desconhecido.")
    if not info.audio:
        raise ValidationError(f"“{info.filename}” não tem trilha de áudio.")
    if opts.quality not in {value for _, value in fmt.qualities}:
        raise ValidationError(f"Valor de {fmt.quality_label.lower()} inválido para {fmt.label}.")
    if fmt.id in ("mp3", "aac", "opus"):
        parse_bitrate(opts.quality)
    if opts.sample_rate:
        if fmt.id == "opus" and opts.sample_rate not in _OPUS_RATES:
            raise ValidationError("O Opus só aceita 8, 12, 16, 24 ou 48 kHz. Use 48.000 Hz ou “Manter original”.")
        if fmt.id == "mp3" and opts.sample_rate > _MP3_MAX_RATE:
            raise ValidationError("O MP3 aceita no máximo 48.000 Hz. Escolha outra taxa ou outro formato.")


def build_args(info: MediaInfo, opts: AudioOptions, output_path: str) -> list[str]:
    fmt = AUDIO_FORMATS[opts.format]
    args = ["-y", "-i", info.path, "-vn", "-map", "0:a:0", "-map_metadata", "0"]
    if fmt.id == "wav":
        args += ["-c:a", opts.quality]                    # pcm_s16le ou pcm_s24le
    elif fmt.id == "flac":
        args += ["-c:a", "flac", "-compression_level", opts.quality]
    else:
        args += ["-c:a", fmt.codec, "-b:a", opts.quality]
    if opts.sample_rate:
        args += ["-ar", str(opts.sample_rate)]
    if opts.channels:
        args += ["-ac", str(opts.channels)]
    args.append(output_path)
    return args


def output_path_for(input_path: str, opts: AudioOptions) -> str:
    """<nome>.<ext>; se colidiria com o próprio original (mesma pasta e extensão), usa '_convertido'."""
    ext = AUDIO_FORMATS[opts.format].ext
    src = Path(input_path)
    same_place = not opts.out_dir or Path(opts.out_dir).resolve() == src.resolve().parent
    suffix = "_convertido" if same_place and src.suffix.lower() == ext else ""
    return build_output_path(input_path, opts.out_dir or None, suffix, ext)


def build_job(info: MediaInfo, opts: AudioOptions, kind: str = KIND_CONVERT) -> Job:
    validate_options(opts, info)
    output = output_path_for(info.path, opts)
    return Job(name=info.filename, kind=kind, input_path=info.path, output_path=output,
               duration=info.duration, ffmpeg_args=build_args(info, opts, output),
               extra={"format": opts.format, "quality": opts.quality})
