"""Testes da Etapa 6: página inicial, configurações, atalhos personalizáveis e tema."""
from __future__ import annotations

import json
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace

from core import ffmpeg as ff
from core.task_manager import Job, TaskState
from ui import theme
from utils import shortcuts as sc
from utils.config import Config

FFMPEG, FFPROBE = ff.check_tools()

try:
    _t = tk.Tk()
    _t.destroy()
    HAS_DISPLAY = True
except tk.TclError:
    HAS_DISPLAY = False


class ShortcutLogicTests(unittest.TestCase):
    def test_build_sequence(self):
        self.assertEqual(sc.build_sequence("o", True, False, False), "<Control-o>")
        self.assertEqual(sc.build_sequence("O", True, True, False), "<Control-Shift-O>")
        self.assertEqual(sc.build_sequence("3", True, False, False), "<Control-Key-3>")   # nunca "<Control-3>"
        self.assertEqual(sc.build_sequence("F2", False, False, False), "<F2>")
        self.assertEqual(sc.build_sequence("comma", True, False, False), "<Control-comma>")
        self.assertEqual(sc.build_sequence("k", True, False, True), "<Control-Alt-k>")
        self.assertIsNone(sc.build_sequence("Control_L", True, False, False))             # só modificador
        self.assertIsNone(sc.build_sequence("Shift_R", False, True, False))

    def test_validate_sequence(self):
        self.assertEqual(sc.validate_sequence("<Control-k>"), "")
        self.assertEqual(sc.validate_sequence("<Alt-Key-1>"), "")
        self.assertEqual(sc.validate_sequence("<F6>"), "")
        self.assertEqual(sc.validate_sequence("<Escape>"), "")
        self.assertIn("Ctrl", sc.validate_sequence("<k>"))                  # letra solta atrapalharia a digitação
        self.assertIn("Ctrl", sc.validate_sequence("<Shift-K>"))

    def test_unique_ids_and_defaults(self):
        ids = [s.id for s in sc.SHORTCUTS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(sc.shortcut_text("goto_converter"), "Ctrl + 2")
        self.assertEqual(sc.shortcut_text("goto_nada"), "")

    def test_overrides_apply_by_id_and_only_to_that_entry(self):
        eff = {s.id: s for s in sc.effective_shortcuts({"goto_converter": "<Control-Key-9>"})}
        self.assertEqual(eff["goto_converter"].sequence, "<Control-Key-9>")
        self.assertEqual(eff["goto_converter_quick"].sequence, "<Control-e>")     # o atalho rápido não muda
        self.assertEqual(sc.shortcut_text("goto_converter", {"goto_converter": "<Control-Key-9>"}), "Ctrl + 9")

    def test_conflicts(self):
        self.assertEqual(sc.find_conflict("<Control-o>", {}).id, "open_file")
        self.assertIsNone(sc.find_conflict("<Control-o>", {}, ignore_id="open_file"))
        self.assertIsNone(sc.find_conflict("<Control-k>", {}))
        # Shift + letra também colide com a variante de Caps Lock
        self.assertEqual(sc.find_conflict("<Control-Shift-o>", {}).id, "open_files")
        # depois de personalizar, a sequência antiga fica livre e a nova passa a ser ocupada
        custom = {"open_file": "<Control-k>"}
        self.assertIsNone(sc.find_conflict("<Control-o>", custom))
        self.assertEqual(sc.find_conflict("<Control-k>", custom).id, "open_file")


class ConfigAndThemeTests(unittest.TestCase):
    def test_reset_settings_keeps_history(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Config(Path(d) / "s.json")
            cfg.set("max_concurrent", 4)
            cfg.set("shortcuts", {"open_file": "<Control-k>"})
            cfg.add_recent_file("a.mp4", "Conversão", "2026-11-18 10:00")
            cfg.increment_completed()
            cfg.reset_settings()
            self.assertEqual(cfg.get("max_concurrent"), 1)
            self.assertEqual(cfg.get("shortcuts"), {})
            self.assertEqual(len(cfg.get("recent_files")), 1)
            self.assertEqual(cfg.get("tasks_completed"), 1)
            cfg.clear_history()
            self.assertEqual((cfg.get("recent_files"), cfg.get("tasks_completed")), ([], 0))

    def test_palettes(self):
        try:
            blue = theme.ACCENT
            self.assertEqual(theme.set_theme("dark-purple"), "dark-purple")
            self.assertNotEqual(theme.ACCENT, blue)
            self.assertEqual(theme.STATE_COLORS["running"], theme.ACCENT)
            self.assertEqual(theme.CURRENT_THEME, "dark-purple")
            self.assertEqual(theme.set_theme("inexistente"), "dark")          # valor inválido → padrão
            self.assertEqual(theme.ACCENT, blue)
        finally:
            theme.set_theme("dark")

    def test_settings_json_is_created_on_first_run_and_is_valid(self):
        if not HAS_DISPLAY:
            self.skipTest("sem display")
        from ui.main_window import MainWindow
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config" / "settings.json"
            app = MainWindow(Config(path))
            try:
                self.assertTrue(path.exists())
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data["max_concurrent"], 1)
            finally:
                app.destroy()


def spin(app, seconds=0.3, until=None):
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        if until and until():
            return True
        time.sleep(0.02)
    return bool(until and until())


@unittest.skipUnless(HAS_DISPLAY, "sem display (use xvfb-run)")
class Stage6UiTests(unittest.TestCase):
    def setUp(self):
        from ui.main_window import MainWindow
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.app = MainWindow(Config(self.dir / "settings.json"))
        self.app.update()
        self.app.focus_force()
        self.app.update()
        self.dialogs = []
        import ui.settings_view as sv
        import ui.shortcuts_view as sh
        import ui.home as hm
        self._patched = []
        for module in (sv, sh, hm):
            original = module.message_dialog
            self._patched.append((module, original))
            module.message_dialog = self._fake_dialog

    def _fake_dialog(self, parent, title, message, **kw):
        self.dialogs.append((title, message))
        return self.answer if hasattr(self, "answer") else True

    def tearDown(self):
        for module, original in self._patched:
            module.message_dialog = original
        theme.set_theme("dark")
        self.app.tasks.cancel_all()
        spin(self.app, 8, until=lambda: self.app.tasks.active_count == 0)
        self.app.destroy()
        self.tmp.cleanup()

    def press(self, sequence):
        self.app.event_generate(sequence)
        self.app.update()

    # ------------------------------------------------------------------ início
    def test_all_sections_are_now_real_views(self):
        from ui.main_window import VIEW_CLASSES
        for key in VIEW_CLASSES:
            self.app.navigate(key)
            self.assertNotEqual(type(self.app.current_view).__name__, "PlaceholderView", key)
            self.assertNotEqual(type(self.app.current_view).__name__, "ErrorView", key)

    def test_home_tiles_and_tool_cards(self):
        self.app.navigate("home")
        home = self.app.current_view
        if self.app.app.tools_ok:
            self.assertIn(self.app.app.ffmpeg.version, home.tiles["ffmpeg"].value.cget("text"))
            self.assertFalse(home.warning.winfo_ismapped())
        self.assertEqual(home.tiles["done"].value.cget("text"), "0")
        texts = []

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, tk.Label):
                    texts.append(c.cget("text"))
                walk(c)
        walk(home.page.inner)
        for name in ("Conversor de vídeo", "Compressor", "Extrator de áudio", "Extrator de frames",
                     "Analisador de mídia", "Cortador de vídeo", "Conversor de áudio"):
            self.assertIn(name, texts)
        self.assertIn("Ctrl + 2", texts)

    def test_home_tool_card_click_navigates(self):
        from ui.home import _ToolCard
        self.app.navigate("home")
        home = self.app.current_view
        cards = []

        def find(w):
            for c in w.winfo_children():
                if isinstance(c, _ToolCard):
                    cards.append(c)
                find(c)
        find(home.page.inner)
        self.assertEqual(len(cards), 7)
        cards[3].event_generate("<Button-1>")           # 4º cartão: Extrator de frames
        self.app.update()
        self.assertEqual(self.app.current_key, "frames")

    @unittest.skipUnless(FFMPEG.ok, "FFmpeg indisponível")
    def test_home_updates_after_real_job_and_lists_recent_file(self):
        self.app.navigate("home")
        home = self.app.current_view
        self.assertIn("Nada processado", self._all_text(home.recent_box))
        out = str(self.dir / "saida.mkv")
        job = self.app.tasks.add(Job(
            name="teste.mp4", kind="Conversão", output_path=out, duration=1.0,
            ffmpeg_args=["-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=25:duration=1",
                         "-c:v", "libx264", "-preset", "ultrafast", out]))
        self.assertTrue(spin(self.app, 30, until=lambda: job.state == TaskState.DONE))
        self.assertTrue(spin(self.app, 3, until=lambda: home.tiles["done"].value.cget("text") == "1"))
        spin(self.app, 0.4)
        text = self._all_text(home.recent_box)
        self.assertIn("saida.mkv", text)
        self.assertIn("Conversão", text)
        out_file = Path(out)
        out_file.unlink()                                # arquivo apagado: continua listado, avisando
        home.refresh_recent()
        self.assertIn("arquivo movido ou apagado", self._all_text(home.recent_box))

    def test_home_clear_history(self):
        self.app.settings.add_recent_file(str(self.dir / "x.mp4"), "Corte", "2026-11-18 09:00")
        self.app.navigate("home")
        home = self.app.current_view
        self.assertIn("x.mp4", self._all_text(home.recent_box))
        home._clear_history()                           # diálogo simulado confirma
        self.assertEqual(self.app.settings.get("recent_files"), [])
        self.assertIn("Nada processado", self._all_text(home.recent_box))

    @staticmethod
    def _all_text(widget):
        texts = []

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, tk.Label):
                    texts.append(c.cget("text"))
                walk(c)
        walk(widget)
        return "\n".join(texts)

    # ------------------------------------------------------------------ configurações
    def test_settings_general_saves_and_applies(self):
        self.app.navigate("settings")
        v = self.app.current_view
        v.out.var_folder.set(str(self.dir / "exports"))
        v.var_notify.set("Barra de status e som")
        v.var_concurrent.set("3")
        self.app.focus_force()
        self.press("<Control-s>")                       # Ctrl+S salva a aba Geral
        cfg = self.app.settings
        self.assertEqual(cfg.get("export_dir"), str(self.dir / "exports"))
        self.assertTrue((self.dir / "exports").is_dir(), "a pasta é criada ao salvar")
        self.assertEqual((cfg.get("notifications"), cfg.get("max_concurrent")), ("sound", 3))
        self.assertEqual(self.app.tasks.max_concurrent, 3)
        # persiste em disco
        self.assertEqual(Config(self.dir / "settings.json").get("max_concurrent"), 3)

    def test_settings_rejects_invalid_values_without_saving(self):
        self.app.navigate("settings")
        v = self.app.current_view
        for bad in ("0", "9", "abc", ""):
            self.dialogs.clear()
            v.var_concurrent.set(bad)
            self.assertFalse(v.save(), bad)
            self.assertTrue(self.dialogs, bad)
        self.assertEqual(self.app.settings.get("max_concurrent"), 1)
        v.var_concurrent.set("2")
        v.out.var_folder.set("")
        self.assertFalse(v.save())

    def test_new_defaults_for_tools_come_from_export_dir(self):
        self.app.settings.set("export_dir", str(self.dir / "meus_videos"))
        self.app.navigate("converter")
        self.assertEqual(self.app.current_view.out.var_folder.get(), str(self.dir / "meus_videos"))

    def test_theme_change_offers_restart(self):
        restarted = []
        self.app.app.restart = lambda: restarted.append(True)
        self.app.navigate("settings")
        v = self.app.current_view
        v.var_theme.set(theme.THEME_LABELS["dark-purple"])
        self.answer = True                              # “Reiniciar agora”
        self.assertTrue(v.save())
        self.assertEqual(self.app.settings.get("theme"), "dark-purple")
        self.assertEqual(restarted, [True])
        self.assertTrue(any("Reiniciar" in t for t, _ in self.dialogs))
        # sem mudança de tema não pergunta de novo
        self.dialogs.clear()
        v.var_theme.set(theme.THEME_LABELS["dark"])
        theme.set_theme("dark-purple")                  # simula a execução já em roxo, salvando roxo
        v.var_theme.set(theme.THEME_LABELS["dark-purple"])
        self.assertTrue(v.save())
        self.assertFalse(any("Reiniciar" in t for t, _ in self.dialogs))

    def test_restore_defaults_keeps_history(self):
        cfg = self.app.settings
        cfg.set("max_concurrent", 5)
        cfg.set("shortcuts", {"open_file": "<Control-k>"})
        cfg.add_recent_file("a.mp4", "Corte", "2026-11-18 10:00")
        self.app.navigate("settings")
        v = self.app.current_view
        v._reset()
        self.assertEqual(cfg.get("max_concurrent"), 1)
        self.assertEqual(cfg.get("shortcuts"), {})
        self.assertEqual(len(cfg.get("recent_files")), 1)
        self.assertEqual(v.var_concurrent.get(), "1")
        self.assertEqual(self.app.tasks.max_concurrent, 1)

    def test_settings_tabs_switch(self):
        self.app.navigate("settings")
        v = self.app.current_view
        for tab in ("ffmpeg", "shortcuts", "general"):
            v.show_tab(tab)
            self.app.update()
            self.assertTrue(v.panes[tab].winfo_ismapped(), tab)
            self.assertEqual(sum(p.winfo_ismapped() for p in v.panes.values()), 1)

    @unittest.skipUnless(FFMPEG.ok, "FFmpeg indisponível")
    def test_ffmpeg_tab_shows_status_paths_and_codecs(self):
        self.app.navigate("settings")
        v = self.app.current_view
        v.show_tab("ffmpeg")
        self.assertIn("Funcionando", v.tool_widgets["ffmpeg"]["state"].cget("text"))
        self.assertEqual(v.tool_widgets["ffmpeg"]["path"].cget("text"), self.app.app.ffmpeg.path)
        self.assertEqual(v.tool_widgets["ffmpeg"]["origin"].cget("text"), "PATH do sistema")
        self.assertIn("H.264", self._all_text(v.codec_box))
        self.app.update()
        self.assertFalse(v.help_card.winfo_ismapped())

    @unittest.skipUnless(FFMPEG.ok, "FFmpeg indisponível")
    def test_ffmpeg_tab_custom_path_flow(self):
        import ui.settings_view as sv
        self.app.navigate("settings")
        v = self.app.current_view
        v.show_tab("ffmpeg")
        original = sv.filedialog.askopenfilename
        try:
            sv.filedialog.askopenfilename = lambda **kw: str(self.dir / "nao_e_ffmpeg.exe")
            (self.dir / "nao_e_ffmpeg.exe").write_text("oi")
            v._choose("ffmpeg")
            self.assertTrue(any("inválido" in t for t, _ in self.dialogs))
            self.assertFalse(self.app.app.ffmpeg.ok)
            self.app.update()
            self.assertTrue(v.help_card.winfo_ismapped(), "mostra como instalar quando não funciona")
            sv.filedialog.askopenfilename = lambda **kw: FFMPEG.path
            v._choose("ffmpeg")
            self.assertTrue(self.app.app.ffmpeg.ok)
            self.assertEqual(v.tool_widgets["ffmpeg"]["origin"].cget("text"), "Caminho personalizado")
            v._use_path("ffmpeg")
            self.assertEqual(self.app.settings.get("ffmpeg_path"), "")
            self.assertEqual(v.tool_widgets["ffmpeg"]["origin"].cget("text"), "PATH do sistema")
        finally:
            sv.filedialog.askopenfilename = original

    # ------------------------------------------------------------------ atalhos personalizáveis
    def _change_shortcut(self, shortcut_id, new_sequence):
        """Executa o fluxo “Alterar” com um diálogo de captura simulado."""
        import ui.shortcuts_view as sh
        shortcut = next(s for s in sc.effective_shortcuts(self.app.settings.get("shortcuts")) if s.id == shortcut_id)
        original = sh.CaptureDialog
        sh.CaptureDialog = lambda *a, **k: SimpleNamespace(show=lambda: new_sequence)
        try:
            self.app.current_view.shortcuts_panel._change(shortcut)
        finally:
            sh.CaptureDialog = original

    def test_customizing_a_shortcut_rebinds_it_immediately(self):
        self.app.navigate("settings")
        self._change_shortcut("goto_converter", "<Control-Key-9>")
        self.assertEqual(self.app.settings.get("shortcuts"), {"goto_converter": "<Control-Key-9>"})
        self.app.navigate("home")
        self.press("<Control-Key-9>")
        self.assertEqual(self.app.current_key, "converter")
        self.app.navigate("home")
        self.press("<Control-Key-2>")                    # a antiga não faz mais nada
        self.assertEqual(self.app.current_key, "home")
        self.press("<Control-e>")                        # o atalho rápido continua funcionando
        self.assertEqual(self.app.current_key, "converter")

    def test_customization_survives_restart(self):
        from ui.main_window import MainWindow
        self.app.navigate("settings")
        self._change_shortcut("goto_analyzer", "<Control-Alt-a>")
        cfg_path = self.dir / "settings.json"
        second = MainWindow(Config(cfg_path))
        try:
            second.update()
            second.focus_force()
            second.update()
            second.event_generate("<Control-Alt-a>")
            second.update()
            self.assertEqual(second.current_key, "analyzer")
            self.assertIn("Ctrl + Alt + A", sc.shortcut_text("goto_analyzer", second.settings.get("shortcuts")))
        finally:
            second.destroy()

    def test_restoring_a_shortcut_and_all_shortcuts(self):
        self.app.navigate("settings")
        self._change_shortcut("goto_frames", "<Control-Key-9>")
        panel = self.app.current_view.shortcuts_panel
        panel._restore("goto_frames")
        self.assertEqual(self.app.settings.get("shortcuts"), {})
        self._change_shortcut("goto_frames", "<Control-Key-9>")
        self._change_shortcut("goto_cutter", "<Control-Key-8>")
        panel._restore_all()                              # confirmação simulada: True
        self.assertEqual(self.app.settings.get("shortcuts"), {})
        self.app.navigate("home")
        self.press("<Control-Key-5>")
        self.assertEqual(self.app.current_key, "frames")

    def test_choosing_the_default_again_removes_the_override(self):
        self.app.navigate("settings")
        self._change_shortcut("goto_frames", "<Control-Key-9>")
        self._change_shortcut("goto_frames", "<Control-Key-5>")
        self.assertEqual(self.app.settings.get("shortcuts"), {})

    def test_capture_dialog_rejects_conflicts_and_bare_keys(self):
        from ui.shortcuts_view import CaptureDialog
        self.app.navigate("settings")
        shortcut = next(s for s in sc.SHORTCUTS if s.id == "goto_frames")
        dlg = CaptureDialog(self.app, self.app.app, shortcut)
        ev = lambda keysym, state: SimpleNamespace(keysym=keysym, state=state)
        dlg._on_key(ev("Control_L", 0x4))                 # só o modificador: aguarda
        self.assertIsNone(dlg.result)
        dlg._on_key(ev("k", 0))                           # tecla solta: recusada
        self.assertIn("Ctrl", dlg.error.cget("text"))
        dlg._on_key(ev("o", 0x4))                         # Ctrl+O já é “Abrir arquivo”
        self.assertIn("Abrir arquivo", dlg.error.cget("text"))
        self.assertTrue(dlg.winfo_exists())
        dlg._on_key(ev("k", 0x4))                         # Ctrl+K: livre
        self.assertEqual(dlg.result, "<Control-k>")

    def test_shortcuts_page_lists_every_shortcut(self):
        self.app.navigate("settings")
        v = self.app.current_view
        v.show_tab("shortcuts")
        text = self._all_text(v.shortcuts_panel)
        for s in sc.SHORTCUTS:
            self.assertIn(s.label, text)
            self.assertIn(sc.display_name(s.sequence), text)

    # ------------------------------------------------------------------ reinício
    def test_restart_spawns_new_instance_and_closes(self):
        from ui.main_window import MainWindow
        spawned = []
        other = MainWindow(Config(self.dir / "outra.json"))
        other._spawn_new_instance = lambda: spawned.append(True)
        other.update()
        other.restart()
        self.assertEqual(spawned, [True])
        with self.assertRaises(tk.TclError):
            other.winfo_exists()                          # janela destruída

    def test_restart_can_be_aborted_when_tasks_are_running(self):
        from ui.main_window import MainWindow
        import ui.main_window as mw
        original = mw.message_dialog
        mw.message_dialog = lambda *a, **k: False         # o usuário escolhe “Voltar”
        spawned = []
        other = MainWindow(Config(self.dir / "terceira.json"))
        try:
            other._spawn_new_instance = lambda: spawned.append(True)
            other.update()
            if FFMPEG.ok:
                other.tasks.add(Job(name="x", kind="T", duration=600, ffmpeg_args=[
                    "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25", "-t", "600", "-c:v", "libx264",
                    "-preset", "veryslow", str(self.dir / "x.mp4")], output_path=str(self.dir / "x.mp4")))
                spin(other, 1.5)
                other.restart()
                self.assertEqual(spawned, [])
                self.assertFalse(other._closing)
        finally:
            mw.message_dialog = original
            other.tasks.cancel_all()
            spin(other, 8, until=lambda: other.tasks.active_count == 0)
            other.destroy()


if __name__ == "__main__":
    unittest.main()
