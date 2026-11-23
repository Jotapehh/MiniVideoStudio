"""Transforma os dados do FFprobe num relatório legível, organizado em seções.

Separado da interface para poder ser testado e reutilizado (por exemplo, na lista
de arquivos do conversor e no extrator de frames).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.ffprobe import AudioStream, MediaInfo, VideoStream
from utils.file_utils import format_bitrate, format_duration, format_size


@dataclass
class ReportSection:
    key: str                                  # "file" | "video" | "audio" | "extra"
    title: str
    rows: list[tuple[str, str]] = field(default_factory=list)
    note: str = ""                            # aviso quando a seção não se aplica (ex.: arquivo sem vídeo)


def _channels_text(audio: AudioStream) -> str:
    if not audio.channels:
        return "—"
    names = {1: "Mono", 2: "Estéreo", 6: "Surround 5.1", 8: "Surround 7.1"}
    label = names.get(audio.channels)
    return f"{audio.channels} ({label})" if label else str(audio.channels)


def _fps_text(video: VideoStream) -> str:
    if not video.fps:
        return "—"
    text = f"{video.fps:.3f}".rstrip("0").rstrip(".")
    return f"{text} fps".replace(".", ",")


def _video_rows(v: VideoStream) -> list[tuple[str, str]]:
    codec = v.codec.upper() + (f" — {v.codec_long}" if v.codec_long else "")
    rows = [("Codec de vídeo", codec),
            ("Resolução", f"{v.width}x{v.height}" if v.width and v.height else "—"),
            ("FPS", _fps_text(v)),
            ("Bitrate de vídeo", format_bitrate(v.bitrate))]
    if v.profile:
        rows.append(("Perfil", v.profile))
    if v.pix_fmt:
        rows.append(("Formato de pixel", v.pix_fmt))
    return rows


def _audio_rows(a: AudioStream) -> list[tuple[str, str]]:
    codec = a.codec.upper() + (f" — {a.codec_long}" if a.codec_long else "")
    rows = [("Codec de áudio", codec),
            ("Taxa de amostragem", f"{a.sample_rate:,} Hz".replace(",", ".") if a.sample_rate else "—"),
            ("Canais", _channels_text(a)),
            ("Bitrate de áudio", format_bitrate(a.bitrate))]
    if a.language and a.language != "und":
        rows.append(("Idioma", a.language))
    return rows


def build_report(info: MediaInfo) -> list[ReportSection]:
    """Monta as seções Arquivo, Vídeo, Áudio e (se houver) Extras."""
    file_section = ReportSection("file", "Arquivo", [
        ("Nome do arquivo", info.filename),
        ("Pasta", info.path[: -len(info.filename)].rstrip("/\\") or "—"),
        ("Tamanho", format_size(info.size)),
        ("Formato do contêiner", f"{info.container_label} ({info.container_long})" if info.container_long
         else info.container_label),
        ("Duração", format_duration(info.duration)),
        ("Bitrate total", format_bitrate(info.bitrate)),
    ])

    video = ReportSection("video", "Vídeo")
    if info.video:
        video.rows = _video_rows(info.video)
    else:
        video.note = "Este arquivo não possui trilha de vídeo."

    audio = ReportSection("audio", "Áudio")
    if info.audio:
        audio.rows = _audio_rows(info.audio)
    else:
        audio.note = "Este arquivo não possui trilha de áudio."

    sections = [file_section, video, audio]

    extras = ReportSection("extra", "Outras trilhas")
    for n, a in enumerate(info.audio_streams[1:], start=2):
        lang = f", {a.language}" if a.language and a.language != "und" else ""
        extras.rows.append((f"Áudio {n}", f"{a.codec.upper()} · {_channels_text(a)}{lang}"))
    for n, v in enumerate(info.video_streams[1:], start=2):
        extras.rows.append((f"Vídeo {n}", f"{v.codec.upper()} · {v.width}x{v.height}"))
    if info.subtitle_count:
        extras.rows.append(("Legendas", f"{info.subtitle_count} trilha{'s' if info.subtitle_count != 1 else ''}"))
    if extras.rows:
        sections.append(extras)
    return sections


def report_to_text(sections: list[ReportSection]) -> str:
    """Versão em texto simples do relatório (para copiar para a área de transferência)."""
    lines: list[str] = []
    for section in sections:
        lines.append(f"[{section.title}]")
        if section.note:
            lines.append(f"  {section.note}")
        width = max((len(label) for label, _ in section.rows), default=0)
        lines.extend(f"  {label.ljust(width)}  {value}" for label, value in section.rows)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def one_line_summary(info: MediaInfo) -> str:
    """Resumo curto, ex.: 'MP4 · 1920x1080 · 30 fps · 03:25 · 45,2 MB'."""
    parts = [info.container_label]
    if info.video:
        parts.append(info.resolution_text)
        if info.video.fps:
            parts.append(_fps_text(info.video))
    parts += [format_duration(info.duration), format_size(info.size)]
    return " · ".join(parts)
