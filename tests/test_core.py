"""Testes da Etapa 1 (núcleo). Usam o FFmpeg/FFprobe reais instalados no sistema.

Execute na pasta do projeto:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from core import ffmpeg as ff
from core import ffprobe
from core.task_manager import Job, TaskManager, TaskState
from utils import file_utils as fu
from utils import validators as v
from utils.config import Config

FFMPEG, FFPROBE = ff.check_tools()


def wait_until(manager: TaskManager, predicate, timeout: float = 60.0) -> bool:
    """Bombeia os eventos (como a UI faria com root.after) até a condição ficar verdadeira."""
    end = time.time() + timeout
    while time.time() < end:
        manager.pump()
        if predicate():
            return True
        time.sleep(0.05)
    return False


@unittest.skipUnless(FFMPEG.ok and FFPROBE.ok, "FFmpeg/FFprobe não disponíveis")
class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.sample = str(cls.dir / "amostra.mp4")
        result = ff.run_ffmpeg([
            "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=3",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=3:sample_rate=44100",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", cls.sample,
        ], ffmpeg_path=FFMPEG.path)
        assert result.ok, result.stderr_tail

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # ---------------------------------------------------------------- ffprobe
    def test_probe_reads_metadata(self):
        info = ffprobe.probe(self.sample, FFPROBE.path)
        self.assertEqual(info.resolution_text, "320x240")
        self.assertAlmostEqual(info.video.fps, 25.0, places=1)
        self.assertAlmostEqual(info.duration, 3.0, delta=0.3)
        self.assertEqual(info.video.codec, "h264")
        self.assertEqual(info.audio.codec, "aac")
        self.assertEqual(info.audio.sample_rate, 44100)
        self.assertEqual(info.audio.channels, 1)
        self.assertEqual(info.container_label, "MP4")
        self.assertGreater(info.size, 0)

    def test_probe_errors_are_friendly(self):
        with self.assertRaises(ffprobe.ProbeError):
            ffprobe.probe(str(self.dir / "nao_existe.mp4"), FFPROBE.path)
        junk = self.dir / "lixo.mp4"
        junk.write_bytes(b"isto nao e um video" * 50)
        with self.assertRaises(ffprobe.ProbeError):
            ffprobe.probe(str(junk), FFPROBE.path)

    # ---------------------------------------------------------------- ffmpeg
    def test_encoders_detected(self):
        enc = ff.list_encoders(FFMPEG.path)
        self.assertIn("libx264", enc["video"])
        self.assertIn("aac", enc["audio"])

    def test_friendly_error_translation(self):
        self.assertIn("não encontrado", ff.friendly_error("x: No such file or directory"))
        self.assertIn("corrompido", ff.friendly_error("Invalid data found when processing input"))

    # ---------------------------------------------------------------- task manager
    def test_conversion_job_reports_real_progress(self):
        out = str(self.dir / "convertido.mkv")
        manager = TaskManager(ffmpeg_path=FFMPEG.path)
        seen: list[tuple[str, float]] = []
        manager.subscribe(lambda ev, job: seen.append((ev, job.progress)))
        job = manager.add(Job(
            name="amostra.mp4", kind="Conversão", input_path=self.sample, output_path=out, duration=3.0,
            ffmpeg_args=["-y", "-i", self.sample, "-c:v", "libx264", "-c:a", "aac", out],
        ))
        self.assertTrue(wait_until(manager, lambda: job.is_finished))
        self.assertEqual(job.state, TaskState.DONE, job.message + job.detail)
        self.assertEqual(job.progress, 1.0)
        self.assertGreater(job.output_size, 0)
        self.assertTrue(Path(out).exists())
        self.assertEqual(seen[0][0], "added")
        self.assertEqual(seen[-1][0], "finished")
        values = [p for _, p in seen]
        self.assertEqual(values, sorted(values), "o progresso nunca deve voltar para trás")

    def test_cancel_running_job_removes_partial_output(self):
        out = str(self.dir / "longo.mp4")
        manager = TaskManager(ffmpeg_path=FFMPEG.path)
        job = manager.add(Job(
            name="longo", kind="Teste", output_path=out, duration=600,
            ffmpeg_args=["-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-t", "600",
                         "-c:v", "libx264", "-preset", "veryslow", out],
        ))
        self.assertTrue(wait_until(manager, lambda: job.state == TaskState.RUNNING and job.progress > 0
                                   or job.message.startswith("Processando"), timeout=20))
        manager.cancel(job.id)
        self.assertTrue(wait_until(manager, lambda: job.is_finished, timeout=20))
        self.assertEqual(job.state, TaskState.CANCELLED)
        self.assertFalse(Path(out).exists(), "saída parcial deve ser apagada")

    def test_error_job_has_friendly_message(self):
        out = str(self.dir / "erro.mp4")
        manager = TaskManager(ffmpeg_path=FFMPEG.path)
        job = manager.add(Job(name="x", kind="Teste", output_path=out,
                              ffmpeg_args=["-y", "-i", str(self.dir / "inexistente.mp4"), out]))
        self.assertTrue(wait_until(manager, lambda: job.is_finished))
        self.assertEqual(job.state, TaskState.ERROR)
        self.assertIn("não encontrado", job.message)
        self.assertFalse(Path(out).exists())

    def test_queue_respects_concurrency_limit(self):
        for limit in (1, 2):
            manager = TaskManager(max_concurrent=limit, ffmpeg_path=FFMPEG.path)
            jobs = []
            for i in range(4):
                out = str(self.dir / f"fila_{limit}_{i}.mkv")
                jobs.append(manager.add(Job(
                    name=f"j{i}", kind="Teste", output_path=out, duration=3.0,
                    ffmpeg_args=["-y", "-i", self.sample, "-c:v", "libx264", "-preset", "veryfast", out])))
            peak = 0

            def done():
                nonlocal peak
                peak = max(peak, manager.counts()["running"])
                return all(j.is_finished for j in jobs)
            self.assertTrue(wait_until(manager, done, timeout=90))
            self.assertLessEqual(peak, limit)
            self.assertTrue(all(j.state == TaskState.DONE for j in jobs))

    def test_cancel_waiting_job(self):
        manager = TaskManager(max_concurrent=1, ffmpeg_path=FFMPEG.path)
        slow = manager.add(Job(name="a", kind="T", duration=600, ffmpeg_args=[
            "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-t", "600", "-preset", "veryslow",
            str(self.dir / "a.mp4")], output_path=str(self.dir / "a.mp4")))
        waiting = manager.add(Job(name="b", kind="T", ffmpeg_args=["-y", "-i", self.sample, str(self.dir / "b.mp4")]))
        self.assertEqual(waiting.state, TaskState.WAITING)
        manager.cancel(waiting.id)
        self.assertEqual(waiting.state, TaskState.CANCELLED)
        manager.shutdown()
        self.assertTrue(wait_until(manager, lambda: slow.is_finished, timeout=20))
        self.assertEqual(slow.state, TaskState.CANCELLED)


# ---------------------------------------------------------------- utilidades (não dependem do FFmpeg)
class UtilTests(unittest.TestCase):
    def test_parse_time(self):
        self.assertEqual(v.parse_time("90"), 90)
        self.assertEqual(v.parse_time("1:30"), 90)
        self.assertAlmostEqual(v.parse_time("01:02:03,5"), 3723.5)
        for bad in ("", "abc", "1:2:3:4", "-5"):
            with self.assertRaises(v.ValidationError):
                v.parse_time(bad)

    def test_format_time_roundtrip(self):
        self.assertEqual(v.format_time(3723.5), "01:02:03.500")

    def test_parse_resolution_and_bitrate(self):
        self.assertEqual(v.parse_resolution("1280x720"), (1280, 720))
        with self.assertRaises(v.ValidationError):
            v.parse_resolution("1281x720")
        with self.assertRaises(v.ValidationError):
            v.parse_resolution("grande")
        self.assertEqual(v.parse_bitrate("2500K"), "2500k")
        with self.assertRaises(v.ValidationError):
            v.parse_bitrate("rápido")

    def test_parse_int_range(self):
        self.assertEqual(v.parse_int("23", "CRF", 0, 51), 23)
        with self.assertRaises(v.ValidationError):
            v.parse_int("60", "CRF", 0, 51)

    def test_formatting(self):
        self.assertEqual(fu.format_size(1536), "1,5 KB")
        self.assertEqual(fu.format_duration(3725), "1:02:05")
        self.assertEqual(fu.format_duration(65), "01:05")
        self.assertEqual(fu.format_bitrate(2_500_000), "2,50 Mbps")
        self.assertEqual(fu.safe_filename('a:b*c?.mp4'), "a_b_c_.mp4")

    def test_unique_path(self):
        with tempfile.TemporaryDirectory() as d:
            first = Path(d) / "video.mp4"
            first.write_bytes(b"x")
            self.assertEqual(Path(fu.unique_path(first)).name, "video (2).mp4")
            self.assertEqual(Path(fu.build_output_path(str(first), d, "_conv", "mkv")).name, "video_conv.mkv")


class ConfigTests(unittest.TestCase):
    def test_roundtrip_and_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            cfg = Config(path)
            self.assertEqual(cfg.get("max_concurrent"), 1)
            cfg.set("max_concurrent", 3)
            cfg.add_recent_file("a.mp4", "Conversor", "2026-11-14 22:00")
            cfg.increment_completed()
            again = Config(path)
            self.assertEqual(again.get("max_concurrent"), 3)
            self.assertEqual(again.get("recent_files")[0]["path"], "a.mp4")
            self.assertEqual(again.get("tasks_completed"), 1)

    def test_corrupted_file_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            path.write_text("{ isto não é json", encoding="utf-8")
            cfg = Config(path)
            self.assertTrue(cfg.load_warning)
            self.assertEqual(cfg.get("theme"), "dark")
            self.assertTrue(path.with_suffix(".json.bak").exists())

    def test_wrong_types_are_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            path.write_text(json.dumps({"max_concurrent": "muitos", "theme": "dark"}), encoding="utf-8")
            self.assertEqual(Config(path).get("max_concurrent"), 1)


if __name__ == "__main__":
    unittest.main()
