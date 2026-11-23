"""Testes da Etapa 5: extrator de frames e cortador de vídeo (FFmpeg real)."""
from __future__ import annotations

import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path

from core import cutter as ct
from core import ffmpeg as ff
from core import ffprobe
from core import frames as fr
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


def make_video(path, seconds=10, size="640x360", audio=True, keyframe_every=50):
    args = ["-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=25:duration={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    args += ["-c:v", "libx264", "-g", str(keyframe_every), "-pix_fmt", "yuv420p"]
    args += (["-c:a", "aac", "-shortest"] if audio else []) + [str(path)]
    assert ff.run_ffmpeg(args, ffmpeg_path=FFMPEG.path).ok


def run(manager, jobs, timeout=90):
    end = time.time() + timeout
    while time.time() < end and not all(j.is_finished for j in jobs):
        manager.pump()
        time.sleep(0.05)


class PureTests(unittest.TestCase):
    def test_estimate_count(self):
        self.assertEqual(fr.estimate_count(10, 2), 5)
        self.assertEqual(fr.estimate_count(10, 3), 4)
        self.assertEqual(fr.estimate_count(10, 20), 1)
        self.assertIsNone(fr.estimate_count(None, 2))

    def test_time_stamp_is_filename_safe(self):
        self.assertEqual(fr.time_stamp(83.5), "00-01-23.500")

    def test_default_container_follows_source(self):
        class Fake:
            def __init__(self, path):
                self.path = path
        self.assertEqual(ct.default_container(Fake("/a/b.mkv")), "mkv")
        self.assertEqual(ct.default_container(Fake("/a/b.flv")), "mp4")


@unittest.skipUnless(TOOLS_OK, "FFmpeg/FFprobe indisponíveis")
class FramesCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.src = str(cls.dir / "aula.mp4")
        make_video(cls.src)
        cls.info = ffprobe.probe(cls.src, FFPROBE.path)
        cls.out = cls.dir / "out"
        cls.out.mkdir()
        cls.manager = TaskManager(max_concurrent=3, ffmpeg_path=FFMPEG.path)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_preview_is_a_scaled_png(self):
        path = fr.render_preview(self.info, 4.0, str(self.dir / "p.png"), FFMPEG.path, 320, 180)
        probe = ffprobe.probe(path, FFPROBE.path)
        self.assertEqual(probe.resolution_text, "320x180")
        with open(path, "rb") as f:
            self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")

    def test_preview_beyond_the_end_is_clamped_not_an_error(self):
        path = fr.render_preview(self.info, 999, str(self.dir / "fim.png"), FFMPEG.path)
        self.assertTrue(Path(path).stat().st_size > 0)

    def test_single_frame_png_and_jpg(self):
        jobs = [self.manager.add(fr.build_frame_job(self.info, 3.5, fmt, q, str(self.out)))
                for fmt, q in (("png", 2), ("jpg", 5))]
        run(self.manager, jobs)
        self.assertTrue(all(j.state == TaskState.DONE for j in jobs), [j.message for j in jobs])
        png, jpg = (Path(j.output_path) for j in jobs)
        self.assertEqual(png.name, "aula_00-00-03.500.png")
        self.assertEqual(jpg.suffix, ".jpg")
        self.assertEqual(ffprobe.probe(str(png), FFPROBE.path).resolution_text, "640x360")
        with open(jpg, "rb") as f:
            self.assertEqual(f.read(2), b"\xff\xd8")           # assinatura JPEG

    def test_jpg_quality_changes_size(self):
        jobs = [self.manager.add(fr.build_frame_job(self.info, 2.0, "jpg", q, str(self.out))) for q in (2, 20)]
        run(self.manager, jobs)
        self.assertGreater(jobs[0].output_size, jobs[1].output_size)

    def test_interval_extraction_creates_folder_with_expected_count(self):
        job = self.manager.add(fr.build_interval_job(self.info, 2.5, "jpg", 5, str(self.out)))
        run(self.manager, [job])
        self.assertEqual(job.state, TaskState.DONE, job.message + job.detail)
        folder = Path(job.extra["open_path"])
        files = sorted(folder.glob("*.jpg"))
        self.assertEqual(len(files), fr.estimate_count(10, 2.5))       # 4 imagens
        self.assertEqual(job.extra["count"], len(files))
        self.assertIn("imagem", job.message)

    def test_cancelled_interval_extraction_removes_its_folder(self):
        long_src = str(self.dir / "longo.mp4")
        make_video(long_src, seconds=60, size="640x360")
        info = ffprobe.probe(long_src, FFPROBE.path)
        job = self.manager.add(fr.build_interval_job(info, 0.1, "png", 2, str(self.out)))
        end = time.time() + 30
        while time.time() < end and not (job.state == TaskState.RUNNING and Path(job.extra["open_path"]).exists()):
            self.manager.pump()
            time.sleep(0.05)
        time.sleep(0.5)
        self.manager.cancel(job.id)
        run(self.manager, [job], timeout=30)
        self.assertEqual(job.state, TaskState.CANCELLED)
        self.assertFalse(Path(job.extra["open_path"]).exists(), "pasta parcial deve ser apagada")

    def test_two_interval_jobs_get_different_folders(self):
        a = fr.build_interval_job(self.info, 5, "png", 2, str(self.out))
        b = fr.build_interval_job(self.info, 5, "png", 2, str(self.out))
        self.assertNotEqual(a.extra["open_path"], b.extra["open_path"])

    def test_validation(self):
        with self.assertRaises(ValidationError):
            fr.build_frame_job(self.info, 500, "png")                  # além da duração
        with self.assertRaises(ValidationError):
            fr.build_frame_job(self.info, 1, "bmp")
        with self.assertRaises(ValidationError):
            fr.build_interval_job(self.info, 0.01)
        with self.assertRaises(ValidationError):
            fr.build_interval_job(self.info, 60)                       # maior que o vídeo


@unittest.skipUnless(TOOLS_OK, "FFmpeg/FFprobe indisponíveis")
class CutterCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.src = str(cls.dir / "aula.mp4")
        make_video(cls.src)
        cls.info = ffprobe.probe(cls.src, FFPROBE.path)
        cls.out = cls.dir / "out"
        cls.out.mkdir()
        cls.manager = TaskManager(max_concurrent=3, ffmpeg_path=FFMPEG.path)
        cls.encoders = ff.list_encoders(FFMPEG.path)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def cut(self, start, end, mode, container="mp4"):
        job = self.manager.add(ct.build_job(
            self.info, ct.CutOptions(start, end, mode, container, str(self.out)), self.encoders))
        run(self.manager, [job])
        self.assertEqual(job.state, TaskState.DONE, job.message + job.detail)
        return ffprobe.probe(job.output_path, FFPROBE.path), job

    def test_precise_cut_has_exact_length(self):
        out, _ = self.cut(3.2, 7.1, ct.MODE_PRECISE)
        self.assertAlmostEqual(out.duration, 3.9, delta=0.15)
        self.assertTrue(out.has_video and out.has_audio)

    def test_fast_cut_copies_streams_without_recoding(self):
        out, _ = self.cut(2.0, 6.0, ct.MODE_FAST)              # começa num quadro-chave
        self.assertEqual((out.video.codec, out.audio.codec), ("h264", "aac"))
        self.assertAlmostEqual(out.duration, 4.0, delta=0.6)

    def test_fast_cut_is_much_cheaper_than_precise(self):
        _, fast = self.cut(0, 8, ct.MODE_FAST)
        _, precise = self.cut(0, 8, ct.MODE_PRECISE)
        self.assertLessEqual(fast.elapsed, precise.elapsed + 0.5)

    def test_change_container_with_precise_cut(self):
        out, job = self.cut(1, 3, ct.MODE_PRECISE, "webm")
        self.assertEqual(out.container_label, "WebM")
        self.assertAlmostEqual(out.duration, 2.0, delta=0.2)
        self.assertTrue(job.output_path.endswith("aula_corte.webm"))

    def test_fast_cut_to_compatible_container(self):
        out, _ = self.cut(0, 4, ct.MODE_FAST, "mkv")
        self.assertEqual(out.container_label, "Matroska (MKV)")

    def test_validation_messages(self):
        bad = [(ct.CutOptions(5, 4), "maior que o inicial"),
               (ct.CutOptions(-1, 4), "negativo"),
               (ct.CutOptions(0, 500), "passa da duração"),
               (ct.CutOptions(0, 4, ct.MODE_FAST, "webm"), "não pode ser copiado")]
        for opts, fragment in bad:
            with self.assertRaises(ValidationError) as ctx:
                ct.build_job(self.info, opts, self.encoders)
            self.assertIn(fragment, str(ctx.exception))
        # o mesmo formato incompatível funciona no modo preciso
        ct.validate_options(ct.CutOptions(0, 4, ct.MODE_PRECISE, "webm"), self.info, self.encoders)

    def test_never_overwrites_previous_cut(self):
        _, first = self.cut(0, 2, ct.MODE_FAST)
        _, second = self.cut(0, 2, ct.MODE_FAST)
        self.assertNotEqual(first.output_path, second.output_path)


def spin(app, seconds=0.3, until=None):
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        if until and until():
            return True
        time.sleep(0.02)
    return bool(until and until())


@unittest.skipUnless(HAS_DISPLAY and TOOLS_OK, "precisa de display e FFmpeg (use xvfb-run)")
class Stage5UiTests(unittest.TestCase):
    def setUp(self):
        from ui.main_window import MainWindow
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.app = MainWindow(Config(self.dir / "settings.json"))
        self.app.update()
        self.video = self.dir / "palestra.mp4"
        make_video(self.video, seconds=8)

    def tearDown(self):
        self.app.tasks.cancel_all()
        spin(self.app, 8, until=lambda: self.app.tasks.active_count == 0)
        self.app.destroy()
        self.tmp.cleanup()

    def open(self, key):
        self.app.navigate(key)
        view = self.app.current_view
        view.accept_files([str(self.video)])
        self.assertTrue(spin(self.app, 10, until=lambda: view.info is not None))
        return view

    def test_new_sections_are_real_views(self):
        for key in ("frames", "cutter"):
            self.app.navigate(key)
            self.assertNotEqual(type(self.app.current_view).__name__, "PlaceholderView", key)

    def test_frames_view_loads_video_and_shows_preview(self):
        v = self.open("frames")
        self.assertIn("palestra.mp4", v.info_lbl.cget("text"))
        self.assertTrue(spin(self.app, 10, until=lambda: v.preview._photo is not None))
        self.assertEqual(v.preview._photo.width(), 440)           # 16:9 cabe na largura da caixa
        v.time.var.set("00:00:04.000")
        v.time._commit()
        self.assertTrue(spin(self.app, 10, until=lambda: v.preview._request > 1 and v.preview._photo is not None))
        self.assertIn("Posição: 00:04", v.time_info.cget("text"))

    def test_frames_view_steps_and_clamps(self):
        v = self.open("frames")
        v._step(1.0)
        self.assertAlmostEqual(v.time.get(), 1.0, places=2)
        v._step("+f")
        self.assertAlmostEqual(v.time.get(), 1.04, places=2)
        v.time.set(100)                                  # além do fim: limitado à duração
        self.assertLessEqual(v.time.get(), 8.0)
        v.time.var.set("abc")
        v.time._commit()                                 # texto inválido volta ao último valor
        self.assertNotEqual(v.time.var.get(), "abc")

    def test_frames_view_extracts_single_frame_and_interval(self):
        v = self.open("frames")
        v.out.var_folder.set(str(self.dir / "imagens"))
        v.time.set(2.0, notify=False)
        v.extract_single()
        v.var_interval.set("4")
        v._update_estimate()
        self.assertIn("≈ 2 imagens", v.estimate_lbl.cget("text"))
        v.extract_interval()
        jobs = self.app.tasks.jobs
        self.assertEqual({j.kind for j in jobs}, {fr.KIND_FRAME, fr.KIND_FRAMES})
        self.assertTrue(spin(self.app, 60, until=lambda: all(j.state == TaskState.DONE for j in jobs)))
        self.assertTrue((self.dir / "imagens" / "palestra_00-00-02.000.png").exists())
        self.assertEqual(len(list((self.dir / "imagens" / "palestra_frames").glob("*.png"))), 2)

    def test_frames_view_rejects_bad_interval(self):
        v = self.open("frames")
        v.var_interval.set("0")
        with self.assertRaises(ValidationError):
            v._interval()
        v.var_interval.set("x")
        with self.assertRaises(ValidationError):
            v._interval()

    def test_frames_view_rejects_audio_only_file(self):
        audio = self.dir / "so.wav"
        ff.run_ffmpeg(["-y", "-f", "lavfi", "-i", "sine=duration=1", str(audio)], ffmpeg_path=FFMPEG.path)
        self.app.navigate("frames")
        v = self.app.current_view
        shown = []
        import ui.single_video as sv
        original = sv.message_dialog
        sv.message_dialog = lambda *a, **k: shown.append(a[2])
        try:
            v.accept_files([str(audio)])
            spin(self.app, 8, until=lambda: bool(shown))
        finally:
            sv.message_dialog = original
        self.assertIsNone(v.info)
        self.assertTrue(any("vídeo" in m for m in shown))

    def test_cutter_view_defaults_and_length_label(self):
        v = self.open("cutter")
        self.assertEqual(v.var_container.get(), "MP4")
        self.assertAlmostEqual(v.end_time.get(), 8.0, places=1)
        v.start_time.set(2.0)
        self.assertIn("00:00:06.000", v.length_lbl.cget("text"))
        v.start_time.set(7.9)
        v.end_time.set(2.0)
        self.assertIn("maior que o inicial", v.length_lbl.cget("text"))

    def test_cutter_view_warns_about_incompatible_fast_cut(self):
        v = self.open("cutter")
        v.var_container.set("WebM")
        v._on_option_change()
        self.assertIn("não pode ser copiado", v.hint_lbl.cget("text"))
        v.var_mode.set(ct.MODE_PRECISE)
        v._on_option_change()
        self.assertEqual(v.hint_lbl.cget("text"), "")

    def test_cutter_view_cuts_through_the_ui(self):
        v = self.open("cutter")
        v.out.var_folder.set(str(self.dir / "cortes"))
        v.var_mode.set(ct.MODE_PRECISE)
        v.start_time.set(2.0, notify=False)
        v.end_time.set(5.0, notify=False)
        v.start()
        jobs = [j for j in self.app.tasks.jobs if j.kind == ct.KIND]
        self.assertEqual(len(jobs), 1)
        self.assertTrue(spin(self.app, 60, until=lambda: jobs[0].state == TaskState.DONE))
        out = ffprobe.probe(jobs[0].output_path, FFPROBE.path)
        self.assertAlmostEqual(out.duration, 3.0, delta=0.2)
        self.assertTrue(spin(self.app, 3, until=lambda: self.app.settings.get("tasks_completed") == 1))

    def test_ctrl_s_saves_cutter_mode(self):
        self.app.navigate("cutter")
        v = self.app.current_view
        v.var_mode.set(ct.MODE_PRECISE)
        self.app.focus_force()
        self.app.update()
        self.app.event_generate("<Control-s>")
        self.app.update()
        self.assertEqual(self.app.settings.get_tool_settings("cutter")["mode"], ct.MODE_PRECISE)

    def test_task_row_for_interval_job_offers_open_folder(self):
        from core.task_manager import Job
        from ui.task_panel import TaskRow
        job = Job(name="x.mp4", kind=fr.KIND_FRAMES, extra={"open_path": str(self.dir)})
        job.state, job.message = TaskState.DONE, "3 imagem(ns) salva(s)"
        row = TaskRow(self.app.host, job, self.app.tasks)
        texts = [b.cget("text") for b in row.buttons.winfo_children()]
        self.assertTrue(any("Abrir pasta" in t for t in texts), texts)
        self.assertIn("3 imagem", row.msg_lbl.cget("text"))
        row.destroy()


if __name__ == "__main__":
    unittest.main()
