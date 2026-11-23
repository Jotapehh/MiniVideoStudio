"""Testes da Etapa 3: analisador e conversor de vídeo (FFmpeg real).

Para as partes com interface: ``xvfb-run -a python -m unittest discover -s tests -t . -v``.
"""
from __future__ import annotations

import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path

from core import converter as cv
from core import ffmpeg as ff
from core import ffprobe
from core.analyzer import build_report, one_line_summary, report_to_text
from core.task_manager import TaskManager, TaskState
from utils.config import Config
from utils.validators import ValidationError

FFMPEG, FFPROBE = ff.check_tools()
TOOLS_OK = FFMPEG.ok and FFPROBE.ok

try:
    _t = tk.Tk()
    _t.destroy()
    HAS_DISPLAY = True
except tk.TclError:
    HAS_DISPLAY = False


def make_sample(path: str, seconds: int = 2, size: str = "320x240", audio: bool = True, fps: int = 25) -> None:
    args = ["-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate={fps}:duration={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}:sample_rate=44100"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p"] + (["-c:a", "aac", "-shortest"] if audio else []) + [path]
    assert ff.run_ffmpeg(args, ffmpeg_path=FFMPEG.path).ok


def run_jobs(manager: TaskManager, jobs, timeout: float = 120) -> None:
    end = time.time() + timeout
    while time.time() < end and not all(j.is_finished for j in jobs):
        manager.pump()
        time.sleep(0.05)


@unittest.skipUnless(TOOLS_OK, "FFmpeg/FFprobe indisponíveis")
class ConverterCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.sample = str(cls.dir / "origem.mp4")
        make_sample(cls.sample, seconds=2)
        cls.silent = str(cls.dir / "mudo.mp4")
        make_sample(cls.silent, audio=False)
        cls.encoders = ff.list_encoders(FFMPEG.path)
        cls.manager = TaskManager(max_concurrent=2, ffmpeg_path=FFMPEG.path)
        cls.out = cls.dir / "saida"
        cls.out.mkdir()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def convert(self, path, **kw):
        info = ffprobe.probe(path, FFPROBE.path)
        opts = cv.ConvertOptions(out_dir=str(self.out), **kw)
        job = self.manager.add(cv.build_job(info, opts))
        run_jobs(self.manager, [job])
        self.assertEqual(job.state, TaskState.DONE, f"{job.message}\n{job.detail}")
        return ffprobe.probe(job.output_path, FFPROBE.path), job

    def test_every_container_with_its_default_codecs(self):
        expected = {"mp4": "MP4", "mkv": "Matroska (MKV)", "avi": "AVI", "mov": "MOV", "webm": "WebM"}
        for cid, label in expected.items():
            v = cv.codecs_for(cid, "video", self.encoders)[0].id
            a = cv.codecs_for(cid, "audio", self.encoders)[0].id
            out, _ = self.convert(self.sample, container=cid, video_codec=v, audio_codec=a)
            self.assertEqual(out.container_label, label, cid)
            self.assertTrue(out.has_video and out.has_audio, cid)
            self.assertAlmostEqual(out.duration, 2.0, delta=0.4, msg=cid)

    def test_resolution_preset_keeps_aspect_ratio(self):
        out, _ = self.convert(self.sample, container="mp4", height=120)
        self.assertEqual(out.resolution_text, "160x120")

    def test_custom_resolution_and_fps(self):
        out, _ = self.convert(self.sample, container="mkv", size=(200, 100), fps=10)
        self.assertEqual(out.resolution_text, "200x100")
        self.assertAlmostEqual(out.video.fps, 10.0, places=1)

    def test_video_bitrate_is_respected(self):
        out, _ = self.convert(self.sample, container="mp4", video_bitrate="400k")
        self.assertLess(out.video.bitrate, 700_000)

    def test_remove_audio(self):
        out, _ = self.convert(self.sample, container="mp4", audio_codec="none")
        self.assertFalse(out.has_audio)

    def test_source_without_audio_converts_fine(self):
        out, _ = self.convert(self.silent, container="mkv")
        self.assertTrue(out.has_video)
        self.assertFalse(out.has_audio)

    def test_copy_streams_is_lossless_and_fast(self):
        out, _ = self.convert(self.sample, container="mkv", video_codec="copy", audio_codec="copy")
        self.assertEqual(out.video.codec, "h264")
        self.assertEqual(out.audio.codec, "aac")

    def test_never_overwrites_original_or_existing_output(self):
        # mesma pasta, mesma extensão: precisa usar o sufixo "_convertido"
        info = ffprobe.probe(self.sample, FFPROBE.path)
        job = cv.build_job(info, cv.ConvertOptions(container="mp4", out_dir=str(self.dir)))
        self.assertTrue(job.output_path.endswith("origem_convertido.mp4"))
        # destino já existente: acrescenta (2)
        first = self.out / "origem.mp4"
        first.write_bytes(b"x")
        job = cv.build_job(info, cv.ConvertOptions(container="mp4", out_dir=str(self.out)))
        self.assertTrue(job.output_path.endswith("origem (2).mp4"))
        first.unlink()

    def test_incompatible_choices_are_rejected_with_clear_messages(self):
        info = ffprobe.probe(self.sample, FFPROBE.path)
        with self.assertRaises(ValidationError):     # H.264 não cabe em WebM
            cv.build_job(info, cv.ConvertOptions(container="webm", video_codec="copy", audio_codec="copy"))
        with self.assertRaises(ValidationError):     # bitrate inválido
            cv.build_job(info, cv.ConvertOptions(container="mp4", video_bitrate="rápido"))
        with self.assertRaises(ValidationError):     # codec que o contêiner não aceita
            cv.build_job(info, cv.ConvertOptions(container="avi", video_codec="libvpx-vp9"))

    def test_audio_file_is_rejected_by_video_converter(self):
        audio = str(self.dir / "so_audio.mp3")
        self.assertTrue(ff.run_ffmpeg(["-y", "-f", "lavfi", "-i", "sine=duration=1", audio],
                                      ffmpeg_path=FFMPEG.path).ok)
        info = ffprobe.probe(audio, FFPROBE.path)
        with self.assertRaises(ValidationError) as ctx:
            cv.build_job(info, cv.ConvertOptions())
        self.assertIn("vídeo", str(ctx.exception))

    def test_codec_lists_follow_installed_encoders(self):
        ids = [c.id for c in cv.codecs_for("webm", "video", {"video": {"libvpx-vp9"}, "audio": set()})]
        self.assertEqual(ids, ["libvpx-vp9", "copy"])


@unittest.skipUnless(TOOLS_OK, "FFmpeg/FFprobe indisponíveis")
class AnalyzerCoreTests(unittest.TestCase):
    def test_report_has_all_requested_fields(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "exemplo.mp4")
            make_sample(path, seconds=2, size="320x240", fps=25)
            info = ffprobe.probe(path, FFPROBE.path)
        sections = {s.key: s for s in build_report(info)}
        labels = {label for s in sections.values() for label, _ in s.rows}
        for wanted in ("Nome do arquivo", "Duração", "Resolução", "FPS", "Bitrate total", "Codec de vídeo",
                       "Codec de áudio", "Taxa de amostragem", "Canais", "Tamanho", "Formato do contêiner"):
            self.assertIn(wanted, labels)
        values = dict(sections["video"].rows)
        self.assertEqual(values["Resolução"], "320x240")
        self.assertEqual(values["FPS"], "25 fps")
        self.assertEqual(dict(sections["audio"].rows)["Taxa de amostragem"], "44.100 Hz")
        text = report_to_text(list(sections.values()))
        self.assertIn("exemplo.mp4", text)
        self.assertIn("320x240", one_line_summary(info))

    def test_audio_only_file_has_note_instead_of_video(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "som.wav")
            self.assertTrue(ff.run_ffmpeg(["-y", "-f", "lavfi", "-i", "sine=duration=1", path],
                                          ffmpeg_path=FFMPEG.path).ok)
            info = ffprobe.probe(path, FFPROBE.path)
        sections = {s.key: s for s in build_report(info)}
        self.assertTrue(sections["video"].note)
        self.assertFalse(sections["video"].rows)
        self.assertTrue(sections["audio"].rows)


def spin(app, seconds=0.3, until=None) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        if until and until():
            return True
        time.sleep(0.02)
    return bool(until and until())


@unittest.skipUnless(HAS_DISPLAY and TOOLS_OK, "precisa de display e FFmpeg (use xvfb-run)")
class Stage3UiTests(unittest.TestCase):
    def setUp(self):
        from ui.main_window import MainWindow
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.app = MainWindow(Config(self.dir / "settings.json"))
        self.app.update()
        self.sample = str(self.dir / "video.mp4")
        make_sample(self.sample, seconds=2)

    def tearDown(self):
        self.app.tasks.cancel_all()
        spin(self.app, 8, until=lambda: self.app.tasks.active_count == 0)
        self.app.destroy()
        self.tmp.cleanup()

    def test_analyzer_view_shows_file_details(self):
        self.app.navigate("analyzer")
        view = self.app.current_view
        self.assertTrue(view.accept_files([self.sample]))
        self.assertTrue(spin(self.app, 10, until=lambda: view.info is not None))
        texts = []

        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, tk.Label):
                    texts.append(child.cget("text"))
                walk(child)
        walk(view.scroll.inner)
        joined = "\n".join(texts)
        self.assertIn("video.mp4", joined)
        self.assertIn("320x240", joined)
        self.assertIn("H264", joined)
        view.copy_btn.invoke()
        self.assertIn("320x240", view.clipboard_get())

    def test_analyzer_reports_corrupted_file_without_crashing(self):
        bad = self.dir / "quebrado.mp4"
        bad.write_bytes(b"nao sou um video" * 20)
        self.app.navigate("analyzer")
        view = self.app.current_view
        view.load(str(bad))
        spin(self.app, 5, until=lambda: "corrompido" in self.app.message_lbl.cget("text") or view.info is None)
        spin(self.app, 0.5)
        self.assertIsNone(view.info)
        self.assertIn("Não foi possível", self.app.message_lbl.cget("text"))

    def test_converter_view_converts_through_the_ui(self):
        self.app.navigate("converter")
        view = self.app.current_view
        out_dir = self.dir / "convertidos"
        bad = self.dir / "texto.mp4"
        bad.write_bytes(b"lixo" * 30)
        view.accept_files([self.sample, str(bad)])
        self.assertTrue(spin(self.app, 10, until=lambda: not view.files.busy))
        self.assertEqual(len(view.files.valid_items), 1, "o arquivo inválido deve ser marcado e ignorado")
        self.assertIn("Converter 1 arquivo", view.start_btn.cget("text"))
        view.var_container.set("MKV")
        view._refresh_codecs()
        view.var_res.set("480p")
        view._update_controls()
        view.var_outdir.set(str(out_dir))
        view.start()
        self.assertEqual(len(view.files.items), 0, "a lista é esvaziada depois de enfileirar")
        jobs = [j for j in self.app.tasks.jobs if j.kind == "Conversão"]
        self.assertEqual(len(jobs), 1)
        self.assertTrue(spin(self.app, 60, until=lambda: jobs[0].state == TaskState.DONE))
        out = ffprobe.probe(jobs[0].output_path, FFPROBE.path)
        self.assertEqual(out.container_label, "Matroska (MKV)")
        self.assertEqual(out.video.height, 480)
        self.assertTrue(spin(self.app, 3, until=lambda: self.app.settings.get("tasks_completed") == 1))

    def test_converter_validation_messages(self):
        self.app.navigate("converter")
        view = self.app.current_view
        view.var_res.set("Personalizada…")
        view.var_custom_res.set("1281x721")
        with self.assertRaises(ValidationError):
            view.collect_options()
        view.var_custom_res.set("1280x720")
        view.var_fps.set("abc")
        with self.assertRaises(ValidationError):
            view.collect_options()
        view.var_fps.set("30")
        view.var_vbit.set("2500k")
        opts = view.collect_options()
        self.assertEqual((opts.size, opts.fps, opts.video_bitrate), ((1280, 720), 30.0, "2500k"))

    def test_converter_controls_follow_codec_choice(self):
        self.app.navigate("converter")
        view = self.app.current_view
        view.var_container.set("WebM")
        view._refresh_codecs()
        self.assertEqual(view.var_vcodec.get(), "VP9")
        self.assertNotIn("H.264 (recomendado)", view.cb_vcodec.cget("values"))
        view.var_vcodec.set("Copiar sem recodificar")
        view._update_controls()
        self.assertEqual(str(view.cb_res.cget("state")), "disabled")
        view.var_acodec.set("Remover áudio")
        view._update_controls()
        self.assertEqual(str(view.cb_abit.cget("state")), "disabled")

    def test_converter_settings_are_saved_with_ctrl_s_and_restored(self):
        self.app.navigate("converter")
        view = self.app.current_view
        view.var_container.set("MOV")
        view._refresh_codecs()
        view.var_fps.set("24")
        self.app.focus_force()
        self.app.update()
        self.app.event_generate("<Control-s>")
        self.app.update()
        saved = self.app.settings.get_tool_settings("converter")
        self.assertEqual((saved["container"], saved["fps"]), ("MOV", "24"))
        from ui.converter_view import ConverterView
        fresh = ConverterView(self.app.host, self.app.app)
        self.assertEqual((fresh.var_container.get(), fresh.var_fps.get()), ("MOV", "24"))
        fresh.destroy()

    def test_open_file_routing(self):
        self.app.navigate("home")
        self.app._deliver_files([self.sample])
        self.assertEqual(self.app.current_key, "analyzer")
        self.app._deliver_files([self.sample, self.sample])
        self.assertEqual(self.app.current_key, "converter")


if __name__ == "__main__":
    unittest.main()
