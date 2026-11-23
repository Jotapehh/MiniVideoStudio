"""Leitura de metadados de mídia com o FFprobe (saída JSON)."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from core.ffmpeg import popen_kwargs


class ProbeError(RuntimeError):
    """Não foi possível analisar o arquivo (mensagem pronta para o usuário)."""


@dataclass
class VideoStream:
    index: int
    codec: str
    codec_long: str
    width: Optional[int]
    height: Optional[int]
    fps: Optional[float]
    bitrate: Optional[int]
    pix_fmt: str = ""
    profile: str = ""


@dataclass
class AudioStream:
    index: int
    codec: str
    codec_long: str
    sample_rate: Optional[int]
    channels: Optional[int]
    channel_layout: str
    bitrate: Optional[int]
    language: str = ""


@dataclass
class MediaInfo:
    path: str
    filename: str
    size: int
    duration: Optional[float]
    container: str                 # nome técnico (ex.: "mov,mp4,m4a,3gp,3g2,mj2")
    container_long: str
    container_label: str           # nome amigável (ex.: "MP4")
    bitrate: Optional[int]
    video: Optional[VideoStream]   # primeira trilha de vídeo
    audio: Optional[AudioStream]   # primeira trilha de áudio
    video_streams: list[VideoStream] = field(default_factory=list)
    audio_streams: list[AudioStream] = field(default_factory=list)
    subtitle_count: int = 0

    @property
    def has_video(self) -> bool:
        return self.video is not None

    @property
    def has_audio(self) -> bool:
        return self.audio is not None

    @property
    def resolution_text(self) -> str:
        if self.video and self.video.width and self.video.height:
            return f"{self.video.width}x{self.video.height}"
        return "—"


def _int(value: Any) -> Optional[int]:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_fraction(text: Any) -> Optional[float]:
    """'30000/1001' → 29.97 ; '0/0' → None."""
    try:
        num, _, den = str(text).partition("/")
        den_f = float(den) if den else 1.0
        return float(num) / den_f if den_f else None
    except ValueError:
        return None


def friendly_container(format_name: str, filename: str) -> str:
    """Escolhe um nome amigável para o contêiner, usando a extensão para desempatar."""
    ext = Path(filename).suffix.lower().lstrip(".")
    names = format_name.split(",")
    table = {"mp4": "MP4", "mov": "MOV", "m4a": "M4A (AAC)", "mkv": "Matroska (MKV)", "webm": "WebM",
             "avi": "AVI", "flv": "FLV", "mp3": "MP3", "wav": "WAV", "flac": "FLAC", "ogg": "Ogg",
             "opus": "Opus (Ogg)", "aac": "AAC (ADTS)", "ts": "MPEG-TS", "mpg": "MPEG-PS"}
    if ext == "opus" and "ogg" in names:
        return "Opus (Ogg)"
    if ext in table and (ext in names or (ext in ("mkv", "webm") and "matroska" in names)
                         or (ext in ("mp4", "mov", "m4a") and "mp4" in names)):
        return table[ext]
    return names[0].upper() if names and names[0] else "—"


def probe(path: str, ffprobe_path: str = "ffprobe", timeout: float = 30) -> MediaInfo:
    """Analisa um arquivo de mídia. Levanta ProbeError com mensagem amigável em caso de falha."""
    p = Path(path)
    if not p.is_file():
        raise ProbeError("Arquivo não encontrado (foi movido ou apagado?)")
    cmd = [ffprobe_path, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(p)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=timeout, stdin=subprocess.DEVNULL, **popen_kwargs())
    except subprocess.TimeoutExpired:
        raise ProbeError("A análise demorou demais. O arquivo pode estar corrompido ou em um disco lento.") from None
    except OSError as exc:
        raise ProbeError(f"Não foi possível executar o FFprobe: {exc}") from exc
    if out.returncode != 0:
        raise ProbeError("Não foi possível ler este arquivo. Ele pode estar corrompido ou não ser um vídeo/áudio válido.")
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        raise ProbeError("O FFprobe retornou uma resposta inválida para este arquivo.") from None
    streams = data.get("streams") or []
    if not streams:
        raise ProbeError("Nenhuma trilha de vídeo ou áudio foi encontrada neste arquivo.")
    return _build_info(p, data.get("format") or {}, streams)


def _build_info(p: Path, fmt: dict, streams: list[dict]) -> MediaInfo:
    videos: list[VideoStream] = []
    audios: list[AudioStream] = []
    subtitles = 0
    stream_durations: list[float] = []
    for s in streams:
        kind = s.get("codec_type")
        d = _float(s.get("duration"))
        if d:
            stream_durations.append(d)
        if kind == "video":
            if (s.get("disposition") or {}).get("attached_pic"):   # capa de álbum em MP3 etc.
                continue
            fps = _parse_fraction(s.get("avg_frame_rate"))
            if not fps:
                fps = _parse_fraction(s.get("r_frame_rate"))
            videos.append(VideoStream(
                index=s.get("index", 0), codec=s.get("codec_name", "?"), codec_long=s.get("codec_long_name", ""),
                width=_int(s.get("width")), height=_int(s.get("height")), fps=fps,
                bitrate=_int(s.get("bit_rate")), pix_fmt=s.get("pix_fmt", ""), profile=s.get("profile", ""),
            ))
        elif kind == "audio":
            audios.append(AudioStream(
                index=s.get("index", 0), codec=s.get("codec_name", "?"), codec_long=s.get("codec_long_name", ""),
                sample_rate=_int(s.get("sample_rate")), channels=_int(s.get("channels")),
                channel_layout=s.get("channel_layout", ""), bitrate=_int(s.get("bit_rate")),
                language=(s.get("tags") or {}).get("language", ""),
            ))
        elif kind == "subtitle":
            subtitles += 1

    size = _int(fmt.get("size")) or p.stat().st_size
    duration = _float(fmt.get("duration")) or (max(stream_durations) if stream_durations else None)
    bitrate = _int(fmt.get("bit_rate"))
    if not bitrate and duration:
        bitrate = int(size * 8 / duration)          # estimativa quando o contêiner não informa
    name = fmt.get("format_name", "")
    return MediaInfo(
        path=str(p), filename=p.name, size=size, duration=duration, container=name,
        container_long=fmt.get("format_long_name", ""), container_label=friendly_container(name, p.name),
        bitrate=bitrate, video=videos[0] if videos else None, audio=audios[0] if audios else None,
        video_streams=videos, audio_streams=audios, subtitle_count=subtitles,
    )


def get_duration(path: str, ffprobe_path: str = "ffprobe") -> Optional[float]:
    """Atalho: só a duração em segundos (None se não for possível obter)."""
    try:
        return probe(path, ffprobe_path).duration
    except ProbeError:
        return None
