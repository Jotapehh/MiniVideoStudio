"""Mini Video Studio — ponto de entrada.

Uso:
    python main.py            abre o aplicativo
    python main.py --check    só verifica o FFmpeg/FFprobe e sai (útil para diagnóstico)
"""
from __future__ import annotations

import sys

MIN_PYTHON = (3, 10)


def _enable_high_dpi() -> None:
    """No Windows, evita que a interface fique borrada em telas com escala acima de 100%."""
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def _check_cli() -> int:
    from core.ffmpeg import INSTALL_HELP, check_tools
    from utils.config import Config
    cfg = Config()
    statuses = check_tools(cfg.get("ffmpeg_path"), cfg.get("ffprobe_path"))
    for s in statuses:
        print(f"[{'OK' if s.ok else 'ERRO'}] {s.name}: {s.path or '-'} {s.version or ''} {s.error}".rstrip())
    if not all(s.ok for s in statuses):
        print("\n" + INSTALL_HELP)
        return 1
    return 0


def main() -> int:
    if sys.version_info < MIN_PYTHON:
        print(f"O Mini Video Studio precisa do Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} ou mais novo "
              f"(recomendado: 3.14). Versão atual: {sys.version.split()[0]}.", file=sys.stderr)
        return 1
    if "--check" in sys.argv:
        return _check_cli()
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("O Tkinter não está instalado. Reinstale o Python marcando a opção “tcl/tk and IDLE”.", file=sys.stderr)
        return 1

    _enable_high_dpi()
    from utils.config import Config
    settings = Config()
    from ui import theme
    theme.set_theme(settings.get("theme"))      # precisa vir ANTES de importar a janela e os componentes
    from ui.main_window import MainWindow

    app = MainWindow(settings)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
