"""Testes da interface (Etapa 2).

Precisam de um display. No Linux sem tela: ``xvfb-run -a python -m unittest discover -s tests -t . -v``.
No Windows rodam normalmente (a janela aparece e fecha sozinha).
"""
from __future__ import annotations

import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path

from core import ffmpeg as ff
from core.task_manager import Job, TaskState
from utils.config import Config
from utils.shortcuts import SHORTCUTS, display_name, sequences_for

try:
    _probe = tk.Tk()
    _probe.destroy()
    HAS_DISPLAY = True
except tk.TclError:
    HAS_DISPLAY = False

FFMPEG, FFPROBE = ff.check_tools()


def spin(app, seconds: float = 0.3, until=None) -> bool:
    """Roda o loop de eventos do Tkinter por um tempo (ou até a condição ser verdadeira)."""
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        if until and until():
            return True
        time.sleep(0.02)
    return bool(until and until())


class ShortcutTableTests(unittest.TestCase):
    """Não precisam de display."""

    def test_display_names(self):
        self.assertEqual(display_name("<Control-o>"), "Ctrl + O")
        self.assertEqual(display_name("<Control-Shift-O>"), "Ctrl + Shift + O")
        self.assertEqual(display_name("<Control-comma>"), "Ctrl + ,")
        self.assertEqual(display_name("<Control-Key-1>"), "Ctrl + 1")
        self.assertEqual(display_name("<Escape>"), "Esc")
        self.assertEqual(display_name("<F1>"), "F1")

    def test_shift_letter_also_binds_swapped_case(self):
        sc = next(s for s in SHORTCUTS if s.sequence == "<Control-Shift-O>")
        self.assertEqual(sequences_for(sc), ["<Control-Shift-O>", "<Control-Shift-o>"])

    def test_no_duplicate_sequences(self):
        sequences = [s.sequence for s in SHORTCUTS]
        self.assertEqual(len(sequences), len(set(sequences)))


@unittest.skipUnless(HAS_DISPLAY, "sem display (use xvfb-run)")
class WindowTests(unittest.TestCase):
    def setUp(self):
        from ui.main_window import MainWindow
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.app = MainWindow(Config(self.dir / "settings.json"))
        self.app.deiconify()
        self.app.update()
        self.app.focus_force()
        self.app.update()

    def tearDown(self):
        self.app.tasks.cancel_all()
        spin(self.app, 8, until=lambda: self.app.tasks.active_count == 0)
        self.app.destroy()
        self.tmp.cleanup()

    def press(self, sequence: str, widget=None):
        (widget or self.app).event_generate(sequence)
        self.app.update()

    # ------------------------------------------------------------------ navegação
    def test_every_section_opens(self):
        from ui.main_window import VIEW_CLASSES
        for key in VIEW_CLASSES:
            self.app.navigate(key)
            self.assertEqual(self.app.current_key, key)
            self.assertTrue(self.app.title_lbl.cget("text"))
            self.assertTrue(self.app.subtitle_lbl.cget("text"))

    def test_all_shortcut_actions_have_handlers(self):
        from ui.main_window import VIEW_CLASSES
        for s in SHORTCUTS:
            if s.action.startswith("goto_"):
                self.assertIn(s.action[5:], VIEW_CLASSES, s.action)
            else:
                self.assertTrue(hasattr(self.app, f"_act_{s.action}"), s.action)

    def test_number_shortcuts_navigate(self):
        order = ["home", "converter", "compressor", "audio_extractor", "frames", "analyzer", "cutter",
                 "audio_converter"]
        for n, key in enumerate(order, start=1):
            self.press(f"<Control-Key-{n}>")
            self.assertEqual(self.app.current_key, key, f"Ctrl+{n}")
        self.press("<Control-comma>")
        self.assertEqual(self.app.current_key, "settings")
        self.press("<Control-e>")
        self.assertEqual(self.app.current_key, "converter")
        self.press("<Control-i>")
        self.assertEqual(self.app.current_key, "analyzer")
        self.press("<Control-Shift-A>")
        self.assertEqual(self.app.current_key, "audio_extractor")
        self.press("<Control-Shift-C>")
        self.assertEqual(self.app.current_key, "compressor")

    def test_shortcuts_do_not_fire_while_typing(self):
        entry = tk.Entry(self.app.host)
        entry.grid(row=1, column=0)
        entry.focus_force()
        self.app.update()
        self.app.navigate("home")
        self.press("<Control-Key-3>", entry)
        self.assertEqual(self.app.current_key, "home", "digitando em um campo, Ctrl+3 deve ser ignorado")
        self.app.focus_force()
        entry.destroy()

    # ------------------------------------------------------------------ diálogos
    def test_escape_closes_dialog_without_triggering_global_cancel(self):
        from ui.widgets import message_dialog
        result = {}

        def close_with_escape():
            dialog = next(w for w in self.app.winfo_children() if isinstance(w, tk.Toplevel))
            dialog.event_generate("<Escape>")

        self.app.after(200, close_with_escape)
        result["value"] = message_dialog(self.app, "Teste", "Mensagem", cancel_text="Cancelar")
        self.assertFalse(result["value"])

    def test_confirm_dialog_returns_true_on_button(self):
        from ui.widgets import message_dialog

        def click_confirm():
            dialog = next(w for w in self.app.winfo_children() if isinstance(w, tk.Toplevel))
            dialog.close(True)

        self.app.after(200, click_confirm)
        self.assertTrue(message_dialog(self.app, "Teste", "Mensagem", cancel_text="Não"))

    def test_status_message_and_default_hint(self):
        self.app.set_status("Olá", timeout_ms=150)
        self.assertEqual(self.app.message_lbl.cget("text"), "Olá")
        spin(self.app, 0.5)
        self.assertIn("F1", self.app.message_lbl.cget("text"))

    # ------------------------------------------------------------------ tarefas na interface
    @unittest.skipUnless(FFMPEG.ok, "FFmpeg indisponível")
    def test_task_panel_follows_real_job_and_updates_stats(self):
        from ui.task_panel import TaskPanel
        panel = TaskPanel(self.app.host, self.app.tasks)
        panel.grid(row=1, column=0)
        out = str(self.dir / "saida.mkv")
        job = self.app.tasks.add(Job(
            name="teste.mp4", kind="Conversão", output_path=out, duration=2.0,
            ffmpeg_args=["-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=25:duration=2",
                         "-c:v", "libx264", "-preset", "ultrafast", out]))
        spin(self.app, 1, until=lambda: job.id in panel._rows)
        self.assertIn(job.id, panel._rows)
        self.assertTrue(spin(self.app, 30, until=lambda: job.state == TaskState.DONE))
        spin(self.app, 0.4)
        self.assertEqual(panel._rows[job.id].state_lbl.cget("text"), "● Concluído")
        self.assertEqual(self.app.settings.get("tasks_completed"), 1)
        self.assertEqual(self.app.settings.get("recent_files")[0]["path"], out)
        self.assertIn("Pronto", self.app.state_lbl.cget("text"))
        self.app.tasks.remove(job.id)
        spin(self.app, 0.4)
        self.assertNotIn(job.id, panel._rows)
        panel.destroy()

    @unittest.skipUnless(FFMPEG.ok, "FFmpeg indisponível")
    def test_cancel_via_ui_and_quit_waits_for_processes(self):
        out = str(self.dir / "longo.mp4")
        job = self.app.tasks.add(Job(
            name="longo.mp4", kind="Conversão", output_path=out, duration=600,
            ffmpeg_args=["-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-t", "600",
                         "-c:v", "libx264", "-preset", "veryslow", out]))
        spin(self.app, 10, until=lambda: job.state == TaskState.RUNNING and job.message.startswith("Processando"))
        self.assertTrue(spin(self.app, 3, until=lambda: "Processando 1 tarefa" in self.app.state_lbl.cget("text")))
        self.app.tasks.cancel_all()
        self.assertTrue(spin(self.app, 20, until=lambda: job.state == TaskState.CANCELLED))
        self.assertFalse(Path(out).exists())


if __name__ == "__main__":
    unittest.main()
