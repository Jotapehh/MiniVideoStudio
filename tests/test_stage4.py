"""Testes da Etapa 4: compressor, extrator e conversor de áudio (FFmpeg real)."""
from __future__ import annotations

import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path

from core import audio as au
from core import compressor as cp
from core import converter as cv
from core import ffmpeg as ff
from core import ffprobe
from core.task_manager import TaskManager, TaskState
from utils import file_utils as fu
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


def make_video(path, seconds=3, size="1280x720", audio=True):
    args = ["-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=25:duration={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}:sample_rate=44100"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p"] + (["-c:a", "aac", "-shortest"] if audio else []) + [str(path)]
    assert ff.run_ffmpeg(args, ffmpeg_path=FFMPEG.path).ok


def run(manager, jobs, timeout=120):
    end = time.time() + timeout
    while time.time() < end and not all(j.is_finished for j in jobs):
        manager.pump()
        time.sleep(0.05)


class PureTests(unittest.TestCase):
    def test_quality_crf_mapping_roundtrip(self):
        self.assertEqual(cp.crf_to_quality(cp.CRF_BEST), 100)
        self.assertEqual(cp.crf_to_quality(cp.CRF_WORST), 0)
        for crf in range(cp.CRF_BEST, cp.CRF_WORST + 1):
            self.assertEqual(cp.quality_to_crf(cp.crf_to_quality(crf)), crf)
        self.assertEqual(cp.quality_to_crf(-10), cp.CRF_WORST)
        self.assertEqual(cp.quality_to_crf(500), cp.CRF_BEST)

    def test_profiles_are_ordered_by_quality(self):
        crfs = [cp.PROFILES[k].crf for k in ("high", "balanced", "small")]
        self.assertEqual(crfs, sorted(crfs))

    def test_reserved_paths_never_collide(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "saida.mp4"
            first = fu.unique_path(target)
            second = fu.unique_path(target)       # o primeiro ainda não existe em disco
            self.assertNotEqual(first, second)
            self.assertTrue(second.endswith("saida (2).mp4"))
            fu.release_path(first)
            self.assertEqual(fu.unique_path(target), first)   # liberado: volta a ficar disponível
            fu.release_path(first)
            fu.release_path(second)


@unittest.skipUnless(TOOLS_OK, "FFmpeg/FFprobe indisponíveis")
class CompressorCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.src = cls.dir / "video.mp4"
        make_video(cls.src)
        cls.small = cls.dir / "pequeno.mp4"
        make_video(cls.small, seconds=2, size="320x240", audio=False)
        cls.out = cls.dir / "out"
        cls.out.mkdir()
        cls.manager = TaskManager(max_concurrent=3, ffmpeg_path=FFMPEG.path)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def compress(self, path, **kw):
        info = ffprobe.probe(str(path), FFPROBE.path)
        job = self.manager.add(cp.build_job(info, cp.CompressOptions(out_dir=str(self.out), **kw)))
        run(self.manager, [job])
        self.assertEqual(job.state, TaskState.DONE, job.message + job.detail)
        return ffprobe.probe(job.output_path, FFPROBE.path), job

    def test_higher_crf_gives_smaller_file(self):
        _, low = self.compress(self.src, crf=18)
        _, high = self.compress(self.src, crf=35)
        self.assertLess(high.output_size, low.output_size)

    def test_resolution_limit_downscales_but_never_upscales(self):
        out, _ = self.compress(self.src, max_height=360)
        self.assertEqual(out.video.height, 360)
        out, _ = self.compress(self.small, max_height=720)      # já é menor que o limite
        self.assertEqual(out.resolution_text, "320x240")

    def test_output_is_mp4_with_suffix_and_never_overwrites(self):
        fresh = self.dir / "limpa"
        fresh.mkdir()
        info = ffprobe.probe(str(self.src), FFPROBE.path)
        jobs = [self.manager.add(cp.build_job(info, cp.CompressOptions(out_dir=str(fresh)))) for _ in range(2)]
        run(self.manager, jobs)
        job1, job2 = jobs
        self.assertTrue(job1.output_path.endswith("video_comprimido.mp4"))
        self.assertNotEqual(job1.output_path, job2.output_path)

    def test_x265_codec(self):
        out, _ = self.compress(self.src, codec="libx265")
        self.assertEqual(out.video.codec, "hevc")

    def test_same_name_inputs_from_different_folders_do_not_overwrite_each_other(self):
        other = self.dir / "outra"
        other.mkdir()
        twin = other / "video.mp4"
        make_video(twin, seconds=2)
        jobs = [self.manager.add(cp.build_job(ffprobe.probe(str(p), FFPROBE.path),
                                              cp.CompressOptions(out_dir=str(self.out))))
                for p in (self.src, twin)]
        self.assertEqual(len({j.output_path for j in jobs}), 2)
        run(self.manager, jobs)
        self.assertTrue(all(j.state == TaskState.DONE for j in jobs))

    def test_savings_summary_and_extra_flag(self):
        _, job = self.compress(self.src, crf=30)
        self.assertTrue(job.extra["compare"])
        original, final, saved = cp.summarize_savings([job])
        self.assertEqual((original, final), (job.input_size, job.output_size))
        self.assertAlmostEqual(saved, (1 - final / original) * 100)
        self.assertIsNone(cp.summarize_savings([]))

    def test_audio_bitrate_is_not_inflated(self):
        info = ffprobe.probe(str(self.src), FFPROBE.path)
        self.assertLessEqual(float(cp.effective_audio_bitrate(info, "256k").rstrip("k")), 256)

    def test_invalid_options(self):
        info = ffprobe.probe(str(self.src), FFPROBE.path)
        for bad in (cp.CompressOptions(crf=99), cp.CompressOptions(preset="turbo"),
                    cp.CompressOptions(audio_bitrate="alto"), cp.CompressOptions(codec="xyz")):
            with self.assertRaises(ValidationError):
                cp.build_job(info, bad)


@unittest.skipUnless(TOOLS_OK, "FFmpeg/FFprobe indisponíveis")
class AudioCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.video = cls.dir / "clipe.mp4"
        make_video(cls.video, seconds=3, size="160x120")
        cls.silent = cls.dir / "mudo.mp4"
        make_video(cls.silent, seconds=1, size="160x120", audio=False)
        cls.out = cls.dir / "audio"
        cls.out.mkdir()
        cls.manager = TaskManager(max_concurrent=3, ffmpeg_path=FFMPEG.path)
        cls.encoders = ff.list_encoders(FFMPEG.path)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def extract(self, path, fmt, **kw):
        info = ffprobe.probe(str(path), FFPROBE.path)
        opts = au.AudioOptions(format=fmt, quality=au.AUDIO_FORMATS[fmt].default_quality, out_dir=str(self.out), **kw)
        job = self.manager.add(au.build_job(info, opts, au.KIND_EXTRACT))
        run(self.manager, [job])
        self.assertEqual(job.state, TaskState.DONE, f"{fmt}: {job.message}{job.detail}")
        return ffprobe.probe(job.output_path, FFPROBE.path), job

    def test_every_format_extracts_audio_only(self):
        expected = {"mp3": "mp3", "wav": "pcm_s16le", "aac": "aac", "flac": "flac", "opus": "opus"}
        for fmt, codec in expected.items():
            if au.AUDIO_FORMATS[fmt].codec not in self.encoders["audio"]:
                continue
            out, job = self.extract(self.video, fmt)
            self.assertFalse(out.has_video, fmt)
            self.assertEqual(out.audio.codec, codec, fmt)
            self.assertAlmostEqual(out.duration, 3.0, delta=0.5, msg=fmt)
            self.assertTrue(job.output_path.endswith(au.AUDIO_FORMATS[fmt].ext))

    def test_sample_rate_and_channels(self):
        out, _ = self.extract(self.video, "wav", sample_rate=22050, channels=2)
        self.assertEqual((out.audio.sample_rate, out.audio.channels), (22050, 2))

    def test_wav_24_bits_and_flac_level_are_applied(self):
        info = ffprobe.probe(str(self.video), FFPROBE.path)
        args = au.build_args(info, au.AudioOptions(format="wav", quality="pcm_s24le"), "x.wav")
        self.assertIn("pcm_s24le", args)
        args = au.build_args(info, au.AudioOptions(format="flac", quality="8"), "x.flac")
        self.assertEqual(args[args.index("-compression_level") + 1], "8")

    def test_audio_to_audio_conversion_never_overwrites_original(self):
        wav = self.dir / "musica.wav"
        self.assertTrue(ff.run_ffmpeg(["-y", "-f", "lavfi", "-i", "sine=duration=2", str(wav)],
                                      ffmpeg_path=FFMPEG.path).ok)
        info = ffprobe.probe(str(wav), FFPROBE.path)
        job = au.build_job(info, au.AudioOptions(format="wav", quality="pcm_s16le", out_dir=str(self.dir)))
        self.assertTrue(job.output_path.endswith("musica_convertido.wav"))
        fu.release_path(job.output_path)

    def test_video_without_audio_is_rejected(self):
        info = ffprobe.probe(str(self.silent), FFPROBE.path)
        with self.assertRaises(ValidationError) as ctx:
            au.build_job(info, au.AudioOptions())
        self.assertIn("áudio", str(ctx.exception))

    def test_incompatible_sample_rates_are_rejected(self):
        info = ffprobe.probe(str(self.video), FFPROBE.path)
        with self.assertRaises(ValidationError):
            au.build_job(info, au.AudioOptions(format="opus", quality="128k", sample_rate=44100))
        with self.assertRaises(ValidationError):
            au.build_job(info, au.AudioOptions(format="mp3", quality="192k", sample_rate=96000))
        with self.assertRaises(ValidationError):
            au.build_job(info, au.AudioOptions(format="mp3", quality="999k"))

    def test_formats_follow_installed_encoders(self):
        ids = [f.id for f in au.formats_available({"audio": {"libmp3lame", "flac"}, "video": set()})]
        self.assertEqual(ids, ["mp3", "flac"])


def spin(app, seconds=0.3, until=None):
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        if until and until():
            return True
        time.sleep(0.02)
    return bool(until and until())


@unittest.skipUnless(HAS_DISPLAY and TOOLS_OK, "precisa de display e FFmpeg (use xvfb-run)")
class Stage4UiTests(unittest.TestCase):
    def setUp(self):
        from ui.main_window import MainWindow
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.app = MainWindow(Config(self.dir / "settings.json"))
        self.app.update()
        self.video = self.dir / "aula.mp4"
        make_video(self.video, seconds=3, size="640x360")

    def tearDown(self):
        self.app.tasks.cancel_all()
        spin(self.app, 8, until=lambda: self.app.tasks.active_count == 0)
        self.app.destroy()
        self.tmp.cleanup()

    def load(self, key, paths):
        self.app.navigate(key)
        view = self.app.current_view
        view.accept_files([str(p) for p in paths])
        self.assertTrue(spin(self.app, 10, until=lambda: not view.files.busy))
        return view

    def test_all_new_sections_are_real_views(self):
        for key in ("compressor", "audio_extractor", "audio_converter"):
            self.app.navigate(key)
            self.assertNotEqual(type(self.app.current_view).__name__, "PlaceholderView", key)

    def test_compressor_profiles_sync_controls(self):
        self.app.navigate("compressor")
        v = self.app.current_view
        v.apply_profile("high")
        self.assertEqual(v.var_crf.get(), "18")
        self.assertTrue(v.var_preset.get().startswith("slow"))
        v.apply_profile("small")
        self.assertEqual(v.var_crf.get(), "28")
        self.assertIn("720p", v.var_height.get())
        # mexer em um controle manualmente = “Personalizado”
        v.var_crf.set("20")
        v._on_crf()
        self.assertEqual(v.profile_id, "custom")
        self.assertEqual(round(v.var_quality.get()), cp.crf_to_quality(20))
        v.var_quality.set(100)
        v._on_scale()
        self.assertEqual(v.var_crf.get(), str(cp.CRF_BEST))

    def test_compressor_compresses_through_the_ui_and_shows_savings(self):
        v = self.load("compressor", [self.video])
        v.apply_profile("small")
        v.out.var_folder.set(str(self.dir / "saida"))
        v.start()
        jobs = [j for j in self.app.tasks.jobs if j.kind == "Compressão"]
        self.assertEqual(len(jobs), 1)
        self.assertTrue(spin(self.app, 60, until=lambda: jobs[0].state == TaskState.DONE))
        self.assertTrue(spin(self.app, 3, until=lambda: v.summary_lbl.cget("text") != ""))
        text = v.summary_lbl.cget("text")
        self.assertTrue("Economia total" in text or "maior que o original" in text, text)
        self.assertTrue(jobs[0].output_path.endswith("aula_comprimido.mp4"))

    def test_compressor_rejects_bad_crf(self):
        self.app.navigate("compressor")
        v = self.app.current_view
        v.var_crf.set("abc")
        with self.assertRaises(ValidationError):
            v.collect_options()
        v.var_crf.set("80")
        with self.assertRaises(ValidationError):
            v.collect_options()

    def test_audio_extractor_through_the_ui(self):
        v = self.load("audio_extractor", [self.video])
        self.assertEqual(len(v.files.valid_items), 1)
        v.cb_format.set("FLAC")
        v._on_format_change()
        self.assertIn("compressão", v.quality_row.label_widget.cget("text").lower())
        v.out.var_folder.set(str(self.dir / "audios"))
        v.start()
        jobs = [j for j in self.app.tasks.jobs if j.kind == au.KIND_EXTRACT]
        self.assertTrue(spin(self.app, 60, until=lambda: jobs[0].state == TaskState.DONE))
        out = ffprobe.probe(jobs[0].output_path, FFPROBE.path)
        self.assertEqual((out.audio.codec, out.has_video), ("flac", False))

    def test_audio_converter_rejects_files_without_audio(self):
        silent = self.dir / "mudo.mp4"
        make_video(silent, seconds=1, size="160x120", audio=False)
        v = self.load("audio_converter", [silent])
        self.assertEqual(len(v.files.valid_items), 0)
        self.assertEqual(v.files.items[0].error, "Sem trilha de áudio")

    def test_opus_disables_sample_rate_and_options_roundtrip(self):
        self.app.navigate("audio_converter")
        v = self.app.current_view
        v.var_format.set("OPUS")
        v._on_format_change()
        self.assertEqual(str(v.cb_rate.cget("state")), "disabled")
        v.var_format.set("MP3")
        v._on_format_change()
        self.assertEqual(str(v.cb_rate.cget("state")), "readonly")
        v.var_quality.set("320 kbps")
        v.var_channels.set("Mono")
        opts = v.collect_options()
        self.assertEqual((opts.format, opts.quality, opts.channels), ("mp3", "320k", 1))

    def test_ctrl_s_saves_and_restores_per_tool(self):
        self.app.navigate("audio_extractor")
        v = self.app.current_view
        v.var_format.set("WAV")
        v._on_format_change()
        self.app.focus_force()
        self.app.update()
        self.app.event_generate("<Control-s>")
        self.app.update()
        self.assertEqual(self.app.settings.get_tool_settings("audio_extractor")["format"], "WAV")
        from ui.audio_view import AudioExtractorView
        fresh = AudioExtractorView(self.app.host, self.app.app)
        self.assertEqual(fresh.var_format.get(), "WAV")
        fresh.destroy()
        # a outra ferramenta de áudio guarda opções separadas
        self.assertEqual(self.app.settings.get_tool_settings("audio_converter"), {})

    def test_task_row_shows_savings_for_compression(self):
        from core.task_manager import Job
        from ui.task_panel import TaskRow
        job = Job(name="x.mp4", kind="Compressão", extra={"compare": True})
        job.state, job.input_size, job.output_size = TaskState.DONE, 1000, 600
        row = TaskRow(self.app.host, job, self.app.tasks)
        self.assertIn("economia de 40%", row.msg_lbl.cget("text"))
        job.output_size = 1200
        row.refresh()
        self.assertIn("MAIOR", row.msg_lbl.cget("text"))
        row.destroy()


if __name__ == "__main__":
    unittest.main()
