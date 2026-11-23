"""Componentes visuais reutilizáveis com o tema escuro do Mini Video Studio."""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, ttk
from typing import Callable, Optional

from ui import theme
from ui.theme import ICONS
from utils.file_utils import ensure_dir
from utils.validators import ValidationError


# ====================================================================== botões
class Button(tk.Button):
    """Botão plano com efeito de hover. style: primary | secondary | danger | ghost."""

    _COLORS = {
        "primary": (theme.ACCENT_DARK, theme.ACCENT, "#ffffff"),
        "secondary": (theme.FIELD, theme.HOVER, theme.TEXT),
        "danger": ("#7a2f2b", theme.DANGER, "#ffffff"),
        "ghost": (theme.PANEL, theme.HOVER, theme.TEXT_DIM),
    }

    def __init__(self, parent, text: str, command: Optional[Callable] = None, style: str = "secondary",
                 icon: str = "", width: Optional[int] = None, **kw):
        bg, hover, fg = self._COLORS[style]
        self._bg, self._hover, self._fg = bg, hover, fg
        label = f"{ICONS.get(icon, icon)}  {text}" if icon else text
        f = theme.fonts(parent)
        super().__init__(parent, text=label, command=command, bg=bg, fg=fg, activebackground=hover,
                         activeforeground=fg, relief="flat", bd=0, padx=14, pady=7, cursor="hand2",
                         font=f["bold"] if style == "primary" else f["base"], highlightthickness=0,
                         disabledforeground=theme.TEXT_FAINT, width=width or 0, **kw)
        self.bind("<Enter>", lambda e: self["state"] != "disabled" and self.configure(bg=self._hover))
        self.bind("<Leave>", lambda e: self.configure(bg=self._bg))

    def set_enabled(self, enabled: bool) -> None:
        self.configure(state="normal" if enabled else "disabled",
                       cursor="hand2" if enabled else "arrow", bg=self._bg)


# ====================================================================== dicas (tooltips)
class Tooltip:
    """Balão de explicação exibido ao passar o mouse sobre um widget."""

    def __init__(self, widget: tk.Widget, text: str, delay: int = 350):
        self.widget, self.text, self.delay = widget, text, delay
        self._tip: Optional[tk.Toplevel] = None
        self._job: Optional[str] = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _e=None) -> None:
        self._job = self.widget.after(self.delay, self._show)

    def _show(self) -> None:
        if self._tip or not self.widget.winfo_exists():
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        self._tip.configure(bg=theme.BORDER_STRONG)
        label = tk.Label(self._tip, text=self.text, justify="left", wraplength=320, bg=theme.PANEL_ALT,
                         fg=theme.TEXT, padx=10, pady=8, font=theme.fonts(self.widget)["small"])
        label.pack(padx=1, pady=1)
        self._tip.wm_geometry(f"+{x}+{y}")

    def _hide(self, _e=None) -> None:
        if self._job:
            self.widget.after_cancel(self._job)
            self._job = None
        if self._tip:
            self._tip.destroy()
            self._tip = None


# ====================================================================== contêineres
class Card(tk.Frame):
    """Painel com borda discreta e título opcional (visual de painel do editor de referência)."""

    def __init__(self, parent, title: str = "", padding: int = 14, **kw):
        super().__init__(parent, bg=theme.PANEL, highlightbackground=theme.BORDER, highlightthickness=1, **kw)
        f = theme.fonts(parent)
        if title:
            header = tk.Frame(self, bg=theme.PANEL)
            header.pack(fill="x", padx=padding, pady=(10, 0))
            tk.Label(header, text=title, bg=theme.PANEL, fg=theme.TEXT, font=f["heading"]).pack(side="left")
            self.header_actions = tk.Frame(header, bg=theme.PANEL)   # botões à direita do título
            self.header_actions.pack(side="right")
            tk.Frame(self, bg=theme.BORDER, height=1).pack(fill="x", padx=padding, pady=(8, 0))
        self.body = tk.Frame(self, bg=theme.PANEL)
        self.body.pack(fill="both", expand=True, padx=padding, pady=padding)


class PropertyRow(tk.Frame):
    """Linha 'rótulo à esquerda, valor em azul à direita' (painel de propriedades).

    Coloque o campo dentro de ``row.body``. ``help`` mostra um “?” com a explicação.
    Use ``set_label`` / ``set_help`` para mudar os textos depois (ex.: quando o formato muda).
    """

    def __init__(self, parent, label: str, help: str = "", label_width: int = 170):
        super().__init__(parent, bg=theme.PANEL)
        self._fonts = theme.fonts(parent)
        left = tk.Frame(self, bg=theme.PANEL, width=label_width)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        self.label_widget = tk.Label(left, text=label, bg=theme.PANEL, fg=theme.TEXT_DIM, font=self._fonts["base"],
                                     anchor="w")
        self.label_widget.pack(side="left")
        self._left = left
        self._help_label: Optional[tk.Label] = None
        self._tooltip: Optional[Tooltip] = None
        self.body = tk.Frame(self, bg=theme.PANEL)
        self.body.pack(side="left", fill="x", expand=True)
        self.set_help(help)

    def set_label(self, text: str) -> None:
        self.label_widget.configure(text=text)

    def set_help(self, text: str) -> None:
        if self._help_label is not None:
            self._help_label.destroy()
            self._help_label, self._tooltip = None, None
        if text:
            self._help_label = tk.Label(self._left, text=ICONS["help"], bg=theme.FIELD, fg=theme.TEXT_DIM,
                                        font=self._fonts["small"], width=2, cursor="question_arrow")
            self._help_label.pack(side="left", padx=(6, 0))
            self._tooltip = Tooltip(self._help_label, text)


class OutputFolderPicker(tk.Frame):
    """Linha 'Pasta de destino' com botão Escolher… e opção de salvar junto de cada arquivo original."""

    def __init__(self, parent, default_dir: str = "", label_width: int = 140,
                 same_label: str = "Salvar na mesma pasta de cada arquivo original", allow_same: bool = True):
        super().__init__(parent, bg=theme.PANEL)
        self.var_folder = tk.StringVar(value=default_dir)
        self.var_same = tk.BooleanVar(value=False)
        row = PropertyRow(self, "Pasta de destino", "Onde os arquivos gerados serão salvos. O arquivo original "
                          "nunca é alterado nem sobrescrito.", label_width=label_width)
        row.pack(fill="x", pady=3)
        self.entry = ttk.Entry(row.body, textvariable=self.var_folder)
        self.entry.pack(side="left", fill="x", expand=True)
        self.button = Button(row.body, "Escolher…", self._browse, style="secondary", icon="folder")
        self.button.pack(side="left", padx=(8, 0))
        if allow_same:
            ttk.Checkbutton(self, text=same_label, variable=self.var_same).pack(anchor="w", pady=(4, 0),
                                                                               padx=(label_width, 0))
        self.var_same.trace_add("write", lambda *_: self._sync())
        self._sync()

    def _sync(self) -> None:
        same = self.var_same.get()
        self.entry.configure(state="disabled" if same else "normal")
        self.button.set_enabled(not same)

    def _browse(self) -> None:
        folder = filedialog.askdirectory(parent=self, title="Escolher pasta de destino",
                                         initialdir=self.var_folder.get() or None)
        if folder:
            self.var_folder.set(folder)

    def resolve(self) -> str:
        """Pasta de destino pronta para uso ('' = junto do original). Levanta ValidationError."""
        if self.var_same.get():
            return ""
        folder = self.var_folder.get().strip()
        if not folder:
            raise ValidationError("Escolha uma pasta de destino.")
        try:
            return ensure_dir(folder)
        except OSError as exc:
            raise ValidationError(f"Não foi possível usar a pasta de destino: {exc}") from None


class ScrollFrame(tk.Frame):
    """Área rolável. Coloque os filhos em ``.inner``.

    A roda do mouse é tratada por UM único handler global que sobe a hierarquia a partir do widget
    sob o cursor até achar uma área rolável com conteúdo a rolar — assim áreas roláveis aninhadas
    (ex.: a lista de tarefas dentro da tela inteira) funcionam em qualquer ponto.
    """

    _wheel_installed_on: set = set()

    def __init__(self, parent, bg: str = theme.PANEL, **kw):
        super().__init__(parent, bg=bg, **kw)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self._on_scroll_set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._window, width=e.width))
        self._install_wheel(self)

    def _on_scroll_set(self, first, last) -> None:
        """Mostra a barra de rolagem só quando há conteúdo para rolar."""
        self.scrollbar.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.scrollbar.pack_forget()
        elif not self.scrollbar.winfo_ismapped():
            self.scrollbar.pack(side="right", fill="y")

    def can_scroll(self) -> bool:
        return self.inner.winfo_reqheight() > self.canvas.winfo_height()

    @classmethod
    def _install_wheel(cls, widget: tk.Misc) -> None:
        root = widget.winfo_toplevel()
        if str(root) in cls._wheel_installed_on:
            return
        cls._wheel_installed_on.add(str(root))
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            root.bind_all(seq, cls._on_wheel, add="+")

    @staticmethod
    def _on_wheel(event) -> None:
        try:
            widget = event.widget.winfo_containing(event.x_root, event.y_root)
        except (KeyError, tk.TclError):
            return
        step = -1 if (event.num == 4 or getattr(event, "delta", 0) > 0) else 1
        while widget is not None:
            if isinstance(widget, ScrollFrame) and widget.can_scroll():
                widget.canvas.yview_scroll(step * 3, "units")
                return
            widget = widget.master


class EmptyState(tk.Frame):
    """Estado vazio informativo: ícone, título, explicação e ação opcional."""

    def __init__(self, parent, icon: str, title: str, text: str, action_text: str = "",
                 action: Optional[Callable] = None, bg: str = theme.PANEL):
        super().__init__(parent, bg=bg)
        f = theme.fonts(parent)
        tk.Label(self, text=ICONS.get(icon, icon), bg=bg, fg=theme.TEXT_FAINT,
                 font=(f["icon"][0], 30)).pack(pady=(18, 4))
        tk.Label(self, text=title, bg=bg, fg=theme.TEXT, font=f["heading"]).pack()
        tk.Label(self, text=text, bg=bg, fg=theme.TEXT_DIM, font=f["base"], wraplength=420,
                 justify="center").pack(pady=(4, 10))
        if action_text and action:
            Button(self, action_text, action, style="primary").pack(pady=(0, 18))


class Spinner(tk.Canvas):
    """Indicador de carregamento girando (para operações curtas, como analisar um arquivo)."""

    def __init__(self, parent, size: int = 22, color: str = theme.ACCENT, bg: str = theme.PANEL):
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0)
        self._size, self._color = size, color
        self._angle = 0
        self._job: Optional[str] = None
        self._arc = self.create_arc(3, 3, size - 3, size - 3, start=0, extent=100, style="arc",
                                    outline=color, width=3, state="hidden")

    def start(self) -> None:
        self.itemconfigure(self._arc, state="normal")
        if self._job is None:
            self._tick()

    def stop(self) -> None:
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None
        self.itemconfigure(self._arc, state="hidden")      # parado = invisível

    def _tick(self) -> None:
        self._angle = (self._angle - 18) % 360
        self.itemconfigure(self._arc, start=self._angle)
        self._job = self.after(40, self._tick)

    def destroy(self) -> None:
        self.stop()
        super().destroy()


# ====================================================================== trabalho em segundo plano
def run_in_background(widget: tk.Misc, func: Callable, on_done: Callable, on_error: Optional[Callable] = None,
                      poll_ms: int = 40) -> None:
    """Executa ``func()`` numa thread e entrega o resultado ao Tkinter com segurança.

    A thread nunca toca em widgets: o resultado vai para uma fila que é consultada com ``after``
    na thread principal, onde ``on_done(resultado)`` ou ``on_error(exceção)`` são chamados.
    """
    import queue
    import threading
    box: "queue.Queue[tuple[bool, object]]" = queue.Queue()

    def work() -> None:
        try:
            box.put((True, func()))
        except Exception as exc:                 # noqa: BLE001 — repassado ao chamador
            box.put((False, exc))

    state: dict = {"job": None}

    def poll() -> None:
        state["job"] = None
        try:
            ok, value = box.get_nowait()
        except queue.Empty:
            if widget.winfo_exists():
                state["job"] = widget.after(poll_ms, poll)
            return
        if not widget.winfo_exists():
            return
        if ok:
            on_done(value)
        elif on_error:
            on_error(value)

    def cancel_polling(event=None) -> None:
        """Ao destruir o widget, cancela o agendamento pendente (evita 'invalid command name')."""
        if event is not None and event.widget is not widget:
            return
        if state["job"]:
            try:
                widget.after_cancel(state["job"])
            except tk.TclError:
                pass
            state["job"] = None

    widget.bind("<Destroy>", cancel_polling, add="+")
    threading.Thread(target=work, daemon=True).start()
    state["job"] = widget.after(poll_ms, poll)


# ====================================================================== diálogos
class Dialog(tk.Toplevel):
    """Diálogo modal escuro. Esc fecha. Subclasses preenchem ``self.body`` e ``self.buttons``."""

    def __init__(self, parent: tk.Misc, title: str, width: int = 460, height: Optional[int] = None):
        super().__init__(parent)
        self.result = None
        self.withdraw()
        self.title(title)
        self.configure(bg=theme.PANEL)
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        # A barra de botões é empacotada primeiro para nunca ser cortada pelo corpo expansível.
        self.buttons = tk.Frame(self, bg=theme.PANEL_ALT)
        self.buttons.pack(fill="x", side="bottom")
        self.body = tk.Frame(self, bg=theme.PANEL)
        self.body.pack(fill="both", expand=True, padx=20, pady=(18, 8))
        self._size = (width, height)
        self.bind("<Escape>", self._on_escape)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _on_escape(self, _e=None) -> str:
        self.close()
        return "break"                          # impede que o atalho global de Esc também dispare

    def add_button(self, text: str, value, style: str = "secondary") -> Button:
        btn = Button(self.buttons, text, lambda: self.close(value), style=style)
        btn.pack(side="right", padx=(0, 10), pady=10)
        return btn

    def close(self, value=None) -> None:
        self.result = value
        self.grab_release()
        self.destroy()

    def show(self):
        """Exibe centralizado, bloqueia a janela principal até fechar e devolve ``result``."""
        self.update_idletasks()
        w = max(self._size[0], self.winfo_reqwidth())       # a barra de botões nunca é cortada
        h = (self._size[1] or self.winfo_reqheight()) + 6
        parent = self.master.winfo_toplevel()
        x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - h) // 3
        self.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        self.deiconify()
        self.grab_set()
        self.focus_set()
        self.wait_window(self)
        return self.result


def message_dialog(parent: tk.Misc, title: str, message: str, kind: str = "info", confirm_text: str = "OK",
                   cancel_text: str = "", danger: bool = False, detail: str = "") -> bool:
    """Diálogo padrão. Com ``cancel_text`` vira uma confirmação (devolve True/False).

    kind: info | error | warning | question — define o ícone e a cor.
    """
    f = theme.fonts(parent)
    dlg = Dialog(parent, title, width=480)
    icon, color = {"info": ("info", theme.ACCENT), "error": ("cancel", theme.DANGER),
                   "warning": ("info", theme.WARNING), "question": ("help", theme.ACCENT)}[kind]
    row = tk.Frame(dlg.body, bg=theme.PANEL)
    row.pack(fill="x")
    tk.Label(row, text=ICONS[icon], bg=theme.PANEL, fg=color, font=(f["icon"][0], 22)).pack(side="left", anchor="n",
                                                                                          padx=(0, 14))
    tk.Label(row, text=message, bg=theme.PANEL, fg=theme.TEXT, font=f["base"], wraplength=370,
             justify="left", anchor="w").pack(side="left", fill="x", expand=True)
    if detail:
        box = tk.Text(dlg.body, height=6, bg=theme.FIELD, fg=theme.TEXT_DIM, font=f["mono"], relief="flat",
                      wrap="word", highlightthickness=1, highlightbackground=theme.BORDER)
        box.insert("1.0", detail)
        box.configure(state="disabled")
        box.pack(fill="x", pady=(12, 0))
    dlg.add_button(confirm_text, True, "danger" if danger else "primary")
    if cancel_text:
        dlg.add_button(cancel_text, False)
    return bool(dlg.show())
