"""Tabela única de atalhos de teclado.

É usada tanto para registrar os atalhos na janela quanto para montar a página
"Atalhos de teclado" das configurações, então os dois nunca ficam fora de sincronia.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Shortcut:
    id: str                # identificador único (usado para salvar a personalização)
    action: str            # ação executada pela janela principal (ex.: "goto_converter")
    label: str             # descrição exibida ao usuário
    sequence: str          # sequência padrão do Tkinter (ex.: "<Control-o>")
    category: str
    works_while_typing: bool = False   # True: funciona mesmo com o foco em um campo de texto


def _s(action: str, label: str, sequence: str, category: str, typing: bool = False,
       id: str | None = None) -> Shortcut:
    return Shortcut(id or action, action, label, sequence, category, typing)


# Ordem = ordem de exibição na página de atalhos.
SHORTCUTS: list[Shortcut] = [
    _s("open_file", "Abrir arquivo", "<Control-o>", "Arquivos"),
    _s("open_files", "Abrir vários arquivos", "<Control-Shift-O>", "Arquivos"),
    _s("save_settings", "Salvar configurações da ferramenta", "<Control-s>", "Arquivos"),

    _s("goto_home", "Página inicial", "<Control-Key-1>", "Navegação"),
    _s("goto_converter", "Conversor de vídeo", "<Control-Key-2>", "Navegação"),
    _s("goto_compressor", "Compressor", "<Control-Key-3>", "Navegação"),
    _s("goto_audio_extractor", "Extrator de áudio", "<Control-Key-4>", "Navegação"),
    _s("goto_frames", "Extrator de frames", "<Control-Key-5>", "Navegação"),
    _s("goto_analyzer", "Analisador de mídia", "<Control-Key-6>", "Navegação"),
    _s("goto_cutter", "Cortador de vídeo", "<Control-Key-7>", "Navegação"),
    _s("goto_audio_converter", "Conversor de áudio", "<Control-Key-8>", "Navegação"),
    _s("goto_settings", "Abrir configurações", "<Control-comma>", "Navegação"),

    _s("goto_converter", "Abrir conversor de vídeo", "<Control-e>", "Atalhos rápidos", id="goto_converter_quick"),
    _s("goto_compressor", "Abrir compressor", "<Control-Shift-C>", "Atalhos rápidos", id="goto_compressor_quick"),
    _s("goto_audio_extractor", "Abrir extrator de áudio", "<Control-Shift-A>", "Atalhos rápidos",
       id="goto_audio_extractor_quick"),
    _s("goto_analyzer", "Abrir analisador", "<Control-i>", "Atalhos rápidos", id="goto_analyzer_quick"),

    _s("help", "Ajuda", "<F1>", "Geral", typing=True),
    _s("refresh", "Atualizar informações", "<F5>", "Geral"),
    _s("cancel", "Cancelar operação ou fechar diálogo", "<Escape>", "Geral", typing=True),
    _s("quit", "Sair do programa", "<Control-q>", "Geral", typing=True),
]

_KEY_NAMES = {"comma": ",", "period": ".", "slash": "/", "minus": "-", "plus": "+", "Escape": "Esc",
              "Control": "Ctrl", "space": "Espaço", "Return": "Enter", "Tab": "Tab"}
_MODIFIER_KEYSYMS = {"Control_L", "Control_R", "Shift_L", "Shift_R", "Alt_L", "Alt_R", "Meta_L", "Meta_R",
                     "Super_L", "Super_R", "Caps_Lock", "Num_Lock", "ISO_Level3_Shift", "Win_L", "Win_R"}


def display_name(sequence: str) -> str:
    """'<Control-Shift-O>' → 'Ctrl + Shift + O' (texto exibido ao usuário)."""
    parts = [p for p in sequence.strip("<>").split("-") if p != "Key"]
    shown = []
    for p in parts:
        p = _KEY_NAMES.get(p, p)
        shown.append(p.upper() if len(p) == 1 and p.isalpha() else p)
    return " + ".join(shown)


def sequences_for(shortcut: Shortcut | str) -> list[str]:
    """Sequências a registrar. Atalhos com Shift + letra funcionam também com Caps Lock ligado."""
    seq = shortcut if isinstance(shortcut, str) else shortcut.sequence
    parts = seq.strip("<>").split("-")
    if "Shift" in parts and len(parts[-1]) == 1 and parts[-1].isalpha():
        other = parts[-1].swapcase()
        return [seq, "<" + "-".join(parts[:-1] + [other]) + ">"]
    return [seq]


def effective_shortcuts(overrides: dict[str, str] | None = None) -> list[Shortcut]:
    """Aplica as personalizações salvas na configuração ({'id': '<sequência>'})."""
    overrides = overrides or {}
    result = []
    for s in SHORTCUTS:
        custom = overrides.get(s.id)
        if isinstance(custom, str) and custom:
            s = Shortcut(s.id, s.action, s.label, custom, s.category, s.works_while_typing)
        result.append(s)
    return result


def shortcut_text(action: str, overrides: dict[str, str] | None = None) -> str:
    """Atalho principal de uma ação, pronto para exibir (ex.: 'Ctrl + 2'); vazio se não houver."""
    for s in effective_shortcuts(overrides):
        if s.action == action:
            return display_name(s.sequence)
    return ""


# ---------------------------------------------------------------- personalização
def build_sequence(keysym: str, ctrl: bool, shift: bool, alt: bool) -> str | None:
    """Monta a sequência do Tkinter a partir de uma tecla pressionada. None se for só um modificador."""
    if keysym in _MODIFIER_KEYSYMS or not keysym:
        return None
    parts = []
    if ctrl:
        parts.append("Control")
    if alt:
        parts.append("Alt")
    if shift:
        parts.append("Shift")
    if len(keysym) == 1 and keysym.isdigit():
        parts.append(f"Key-{keysym}")            # "<Control-1>" seria lido como clique do mouse
    elif len(keysym) == 1 and keysym.isalpha() and shift:
        parts.append(keysym.upper())
    elif len(keysym) == 1 and keysym.isalpha():
        parts.append(keysym.lower())
    else:
        parts.append(keysym)
    return "<" + "-".join(parts) + ">"


def validate_sequence(sequence: str) -> str:
    """Devolve uma mensagem de erro (vazia se a sequência pode ser usada como atalho global)."""
    inner = sequence.strip("<>").split("-")
    key = inner[-1]
    has_modifier = any(m in inner[:-1] for m in ("Control", "Alt"))
    is_function_key = key.startswith("F") and key[1:].isdigit() or key == "Escape"
    if not (has_modifier or is_function_key):
        return "Use Ctrl ou Alt junto com a tecla (ou uma tecla de função, como F2), para não atrapalhar a digitação."
    return ""


def find_conflict(sequence: str, overrides: dict[str, str] | None, ignore_id: str = "") -> Shortcut | None:
    """Outro atalho que já usa esta sequência (considerando Shift + letra com Caps Lock), se houver."""
    mine = set(sequences_for(sequence))
    for s in effective_shortcuts(overrides):
        if s.id != ignore_id and mine & set(sequences_for(s)):
            return s
    return None
