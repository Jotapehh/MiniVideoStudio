"""Conversão de vídeo: tabelas de codecs/contêineres e montagem do comando do FFmpeg.

Nada aqui depende do Tkinter. A interface escolhe as opções (``ConvertOptions``) e este módulo
devolve um ``Job`` pronto para a fila de tarefas.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.ffprobe import MediaInfo
from core.task_manager import Job
from utils.file_utils import build_output_path
from utils.validators import ValidationError, parse_bitrate


@dataclass(frozen=True)
class CodecInfo:
    id: str            # nome do encoder no FFmpeg (ou "copy" / "none")
    label: str         # nome exibido
    help: str          # explicação simples para o usuário


VIDEO_CODECS: dict[str, CodecInfo] = {c.id: c for c in [
    CodecInfo("libx264", "H.264 (recomendado)",
              "O mais compatível: funciona em praticamente qualquer celular, TV, computador e site."),
    CodecInfo("libx265", "H.265 / HEVC",
              "Gera arquivos bem menores com a mesma qualidade, mas demora mais e alguns aparelhos antigos não reproduzem."),
    CodecInfo("libvpx-vp9", "VP9",
              "Codec aberto, ideal para WebM e para a web. A conversão é mais lenta que o H.264."),
    CodecInfo("libsvtav1", "AV1",
              "Codec moderno, muito eficiente em tamanho. Ainda pouco compatível com aparelhos antigos."),
    CodecInfo("mpeg4", "MPEG-4 (clássico)",
              "Formato antigo, útil para AVI e aparelhos muito velhos. Arquivos maiores."),
    CodecInfo("copy", "Copiar sem recodificar",
              "Não recomprime o vídeo: é muito rápido e não perde qualidade, mas ignora resolução, FPS e bitrate."),
]}

AUDIO_CODECS: dict[str, CodecInfo] = {c.id: c for c in [
    CodecInfo("aac", "AAC", "Padrão para MP4 e MOV. Boa qualidade com arquivos pequenos."),
    CodecInfo("libmp3lame", "MP3", "O formato de áudio mais compatível que existe."),
    CodecInfo("libopus", "Opus", "Qualidade excelente em bitrates baixos. Ideal para WebM e MKV."),
    CodecInfo("libvorbis", "Vorbis", "Alternativa livre ao AAC, usada em WebM."),
    CodecInfo("flac", "FLAC (sem perdas)", "Qualidade perfeita, mas arquivos grandes."),
    CodecInfo("pcm_s16le", "PCM (sem compressão)", "Áudio bruto, com arquivos muito grandes. Usado em edição."),
    CodecInfo("copy", "Copiar sem recodificar", "Mantém o áudio original sem alterações (rápido e sem perda)."),
    CodecInfo("none", "Remover áudio", "O vídeo final não terá som."),
]}


@dataclass(frozen=True)
class ContainerInfo:
    id: str
    label: str
    video: tuple[str, ...]
    audio: tuple[str, ...]
    # Codecs que podem ser COPIADOS (-c copy) para este contêiner (None = sem restrição).
    copy_video: Optional[frozenset] = None
    copy_audio: Optional[frozenset] = None


CONTAINERS: dict[str, ContainerInfo] = {c.id: c for c in [
    ContainerInfo("mp4", "MP4", ("libx264", "libx265", "libsvtav1", "mpeg4", "copy"),
                  ("aac", "libmp3lame", "copy", "none"),
                  frozenset({"h264", "hevc", "mpeg4", "av1", "vp9"}), frozenset({"aac", "mp3", "ac3", "eac3"})),
    ContainerInfo("mkv", "MKV", ("libx264", "libx265", "libvpx-vp9", "libsvtav1", "mpeg4", "copy"),
                  ("aac", "libopus", "libmp3lame", "flac", "copy", "none")),
    ContainerInfo("avi", "AVI", ("mpeg4", "libx264", "copy"), ("libmp3lame", "pcm_s16le", "copy", "none"),
                  frozenset({"mpeg4", "h264", "msmpeg4v3", "mjpeg"}), frozenset({"mp3", "pcm_s16le", "ac3"})),
    ContainerInfo("mov", "MOV", ("libx264", "libx265", "mpeg4", "copy"), ("aac", "pcm_s16le", "copy", "none"),
                  frozenset({"h264", "hevc", "mpeg4", "prores"}), frozenset({"aac", "pcm_s16le", "mp3", "alac"})),
    ContainerInfo("webm", "WebM", ("libvpx-vp9", "libsvtav1", "copy"), ("libopus", "libvorbis", "copy", "none"),
                  frozenset({"vp8", "vp9", "av1"}), frozenset({"vorbis", "opus"})),
]}

# Resoluções predefinidas: rótulo → altura (a largura é calculada mantendo a proporção).
RESOLUTION_PRESETS: list[tuple[str, int]] = [
    ("4K (2160p)", 2160), ("1440p (2K)", 1440), ("Full HD (1080p)", 1080), ("HD (720p)", 720),
    ("480p", 480), ("360p", 360),
]
FPS_PRESETS = ["24", "25", "30", "50", "60"]
VIDEO_BITRATE_PRESETS = ["1000k", "2500k", "5000k", "8000k", "15000k"]
AUDIO_BITRATE_PRESETS = ["96k", "128k", "192k", "256k", "320k"]


def codecs_for(container: str, kind: str, encoders: Optional[dict[str, set[str]]] = None) -> list[CodecInfo]:
    """Codecs oferecidos para o contêiner, filtrados pelo que o FFmpeg instalado realmente suporta."""
    info = CONTAINERS[container]
    table, ids = (VIDEO_CODECS, info.video) if kind == "video" else (AUDIO_CODECS, info.audio)
    available = (encoders or {}).get(kind) or set()
    result = []
    for codec_id in ids:
        if codec_id in ("copy", "none") or not available or codec_id in available:
            result.append(table[codec_id])
    return result


@dataclass
class ConvertOptions:
    container: str = "mp4"
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    height: Optional[int] = None                    # altura-alvo mantendo a proporção (presets)
    size: Optional[tuple[int, int]] = None          # LARGURAxALTURA exatos (personalizada)
    fps: Optional[float] = None
    video_bitrate: Optional[str] = None             # None = qualidade constante automática
    audio_bitrate: Optional[str] = None
    out_dir: str = ""                               # vazio = mesma pasta do original


def _video_quality_args(codec: str, bitrate: Optional[str], container: str) -> list[str]:
    """Parâmetros de qualidade: bitrate escolhido ou qualidade constante (CRF) padrão do codec."""
    args: list[str] = []
    if codec == "libx264":
        args += ["-preset", "medium"] + (["-b:v", bitrate] if bitrate else ["-crf", "23"])
    elif codec == "libx265":
        args += ["-preset", "medium"] + (["-b:v", bitrate] if bitrate else ["-crf", "28"])
        if container in ("mp4", "mov"):
            args += ["-tag:v", "hvc1"]               # necessário para abrir em aparelhos Apple
    elif codec == "libvpx-vp9":
        args += ["-b:v", bitrate] if bitrate else ["-crf", "32", "-b:v", "0"]
        args += ["-row-mt", "1", "-deadline", "good", "-cpu-used", "4"]
    elif codec == "libsvtav1":
        args += ["-preset", "8"] + (["-b:v", bitrate] if bitrate else ["-crf", "35"])
    elif codec == "mpeg4":
        args += ["-b:v", bitrate] if bitrate else ["-q:v", "4"]
    return args


def _audio_args(codec: str, bitrate: Optional[str]) -> list[str]:
    if codec == "none":
        return ["-an"]
    if codec == "copy":
        return ["-c:a", "copy"]
    args = ["-c:a", codec]
    if codec in ("aac", "libmp3lame", "libvorbis"):
        args += ["-b:a", bitrate or "192k"]
    elif codec == "libopus":
        args += ["-b:a", bitrate or "128k"]
    return args


def validate_options(opts: ConvertOptions, info: MediaInfo) -> None:
    """Levanta ValidationError (em português) se as opções não servem para este arquivo."""
    container = CONTAINERS.get(opts.container)
    if not container:
        raise ValidationError(f"Formato de saída desconhecido: {opts.container}.")
    if not info.video:
        raise ValidationError(f"“{info.filename}” não tem trilha de vídeo. Para arquivos de áudio use o "
                              "Conversor de áudio.")
    if opts.video_codec not in container.video:
        raise ValidationError(f"O codec escolhido não é compatível com {container.label}.")
    if opts.audio_codec not in container.audio:
        raise ValidationError(f"O codec de áudio escolhido não é compatível com {container.label}.")
    if opts.video_codec == "copy" and container.copy_video is not None and info.video.codec not in container.copy_video:
        raise ValidationError(
            f"O vídeo de “{info.filename}” ({info.video.codec.upper()}) não pode ser copiado para "
            f"{container.label}. Escolha um codec para recodificar.")
    if (opts.audio_codec == "copy" and info.audio and container.copy_audio is not None
            and info.audio.codec not in container.copy_audio):
        raise ValidationError(
            f"O áudio de “{info.filename}” ({info.audio.codec.upper()}) não pode ser copiado para "
            f"{container.label}. Escolha um codec de áudio para recodificar.")
    for value, label in ((opts.video_bitrate, "Bitrate de vídeo"), (opts.audio_bitrate, "Bitrate de áudio")):
        if value:
            try:
                parse_bitrate(value)
            except ValidationError as exc:
                raise ValidationError(f"{label}: {exc}") from None


def encoding_args(opts: ConvertOptions) -> list[str]:
    """Parte do comando que define COMO codificar (codecs, qualidade, resolução, FPS, áudio, flags).

    É compartilhada com o cortador de vídeo (corte preciso).
    """
    args: list[str] = []
    if opts.video_codec == "copy":
        args += ["-c:v", "copy"]
    else:
        args += ["-c:v", opts.video_codec]
        args += _video_quality_args(opts.video_codec, opts.video_bitrate, opts.container)
        args += ["-pix_fmt", "yuv420p"]              # máxima compatibilidade de reprodução
        if opts.size:
            args += ["-vf", f"scale={opts.size[0]}:{opts.size[1]}"]
        elif opts.height:
            args += ["-vf", f"scale=-2:{opts.height}"]   # -2 mantém a proporção com largura par
        if opts.fps:
            args += ["-r", f"{opts.fps:g}"]
    args += _audio_args(opts.audio_codec, opts.audio_bitrate)
    if opts.container in ("mp4", "mov"):
        args += ["-movflags", "+faststart"]          # permite começar a reproduzir antes de baixar tudo
    return args


def build_args(info: MediaInfo, opts: ConvertOptions, output_path: str) -> list[str]:
    """Argumentos do FFmpeg (depois do executável) para converter ``info`` com ``opts``."""
    args = ["-y", "-i", info.path, "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "0"]
    args += encoding_args(opts)
    args.append(output_path)
    return args


def output_path_for(input_path: str, opts: ConvertOptions) -> str:
    """Caminho de saída sem sobrescrever nada: usa '_convertido' se colidiria com o próprio original."""
    ext = f".{opts.container}"
    same_place = (not opts.out_dir or Path(opts.out_dir).resolve() == Path(input_path).resolve().parent)
    suffix = "_convertido" if same_place and Path(input_path).suffix.lower() == ext else ""
    return build_output_path(input_path, opts.out_dir or None, suffix, ext)


def build_job(info: MediaInfo, opts: ConvertOptions) -> Job:
    """Valida e cria a tarefa de conversão (levanta ValidationError se algo estiver incompatível)."""
    validate_options(opts, info)
    output = output_path_for(info.path, opts)
    return Job(
        name=info.filename, kind="Conversão", input_path=info.path, output_path=output,
        duration=info.duration, ffmpeg_args=build_args(info, opts, output),
        extra={"container": opts.container, "video_codec": opts.video_codec, "audio_codec": opts.audio_codec},
    )
