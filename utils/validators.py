"""Validação e conversão de valores digitados pelo usuário.

Todas as funções levantam ValidationError com uma mensagem em português
pronta para ser exibida na interface.
"""
from __future__ import annotations

import re
from pathlib import Path


class ValidationError(ValueError):
    """Valor inválido informado pelo usuário."""


_TIME_RE = re.compile(r"^\d+(\.\d+)?$")


def parse_time(text: str) -> float:
    """Converte '90', '1:30' ou '01:02:03.5' em segundos."""
    value = (text or "").strip().replace(",", ".")
    if not value:
        raise ValidationError("Informe um tempo (exemplos: 90, 1:30 ou 00:01:30.5).")
    parts = value.split(":")
    if len(parts) > 3 or not all(_TIME_RE.match(p) for p in parts):
        raise ValidationError(f"Tempo inválido: “{text}”. Use HH:MM:SS, MM:SS ou apenas segundos.")
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    return seconds


def format_time(seconds: float) -> str:
    """Segundos → HH:MM:SS.mmm (formato aceito pelo FFmpeg)."""
    seconds = max(0.0, seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def parse_int(text: str, label: str, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        value = int(str(text).strip())
    except ValueError:
        raise ValidationError(f"{label}: digite um número inteiro.") from None
    _check_range(value, label, minimum, maximum)
    return value


def parse_float(text: str, label: str, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        value = float(str(text).strip().replace(",", "."))
    except ValueError:
        raise ValidationError(f"{label}: digite um número.") from None
    _check_range(value, label, minimum, maximum)
    return value


def _check_range(value, label, minimum, maximum) -> None:
    if minimum is not None and value < minimum:
        raise ValidationError(f"{label}: o valor mínimo é {minimum}.")
    if maximum is not None and value > maximum:
        raise ValidationError(f"{label}: o valor máximo é {maximum}.")


def parse_resolution(text: str) -> tuple[int, int]:
    """'1280x720' → (1280, 720). Largura e altura precisam ser pares (exigência dos codecs comuns)."""
    match = re.match(r"^\s*(\d{2,5})\s*[xX×]\s*(\d{2,5})\s*$", text or "")
    if not match:
        raise ValidationError("Resolução inválida. Use LARGURAxALTURA, por exemplo 1280x720.")
    w, h = int(match.group(1)), int(match.group(2))
    if w % 2 or h % 2:
        raise ValidationError("Largura e altura precisam ser números pares (exigência dos codecs de vídeo).")
    return w, h


def parse_bitrate(text: str) -> str:
    """Valida bitrates como '2500k', '2M' ou '128000' e devolve o texto normalizado para o FFmpeg."""
    value = (text or "").strip().lower().replace(" ", "")
    if not re.match(r"^\d+(\.\d+)?[km]?$", value):
        raise ValidationError("Bitrate inválido. Exemplos: 2500k, 5M ou 128k.")
    return value


def require_existing_file(path: str, label: str = "Arquivo") -> str:
    if not path or not Path(path).is_file():
        raise ValidationError(f"{label} não encontrado: {path or '(nenhum selecionado)'}")
    return path


def require_writable_dir(path: str) -> str:
    """Garante que a pasta de destino existe (ou pode ser criada)."""
    if not path:
        raise ValidationError("Escolha uma pasta de destino.")
    p = Path(path)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValidationError(f"Não foi possível usar a pasta de destino: {exc}") from None
    return str(p)
