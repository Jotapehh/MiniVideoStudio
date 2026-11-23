"""Gerenciador de tarefas: fila, execução em threads, progresso e cancelamento.

Como a interface se comunica com este módulo
--------------------------------------------
1. A UI cria um ``Job`` e chama ``manager.add(job)``.
2. Threads de trabalho executam o job e publicam eventos numa ``queue.Queue``
   (elas NUNCA tocam em widgets do Tkinter).
3. A janela principal chama ``manager.pump()`` periodicamente (``root.after``),
   que entrega os eventos aos *listeners* já na thread principal do Tkinter.

Eventos entregues aos listeners: ``listener(event, job)`` com
event em {"added", "updated", "finished", "removed"}.
"""
from __future__ import annotations

import itertools
import queue
import shutil
import threading
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from core.ffmpeg import FFmpegError, FFmpegResult, Progress, friendly_error, run_ffmpeg
from utils.file_utils import file_size, release_path, remove_quietly


class TaskState(str, Enum):
    WAITING = "waiting"
    RUNNING = "running"
    DONE = "done"
    CANCELLED = "cancelled"
    ERROR = "error"


STATE_LABELS = {
    TaskState.WAITING: "Aguardando",
    TaskState.RUNNING: "Processando",
    TaskState.DONE: "Concluído",
    TaskState.CANCELLED: "Cancelado",
    TaskState.ERROR: "Erro",
}
FINISHED_STATES = (TaskState.DONE, TaskState.CANCELLED, TaskState.ERROR)


class JobCancelled(Exception):
    """Levantada dentro de um runner quando o usuário cancela a tarefa."""


class JobError(Exception):
    """Falha de uma tarefa. ``message`` é mostrada ao usuário; ``detail`` guarda o detalhe técnico."""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.message = message
        self.detail = detail


_job_ids = itertools.count(1)


@dataclass
class Job:
    """Uma operação a executar.

    Forma simples: informe ``ffmpeg_args`` (+ ``duration`` para ter porcentagem real).
    Forma avançada: informe ``runner(job, ctx)`` para operações com várias etapas.
    """
    name: str                                   # normalmente o nome do arquivo de entrada
    kind: str                                   # ex.: "Conversão", "Compressão"
    ffmpeg_args: Optional[list[str]] = None
    output_path: Optional[str] = None           # arquivo gerado (apagado se a tarefa falhar/cancelar)
    input_path: Optional[str] = None
    duration: Optional[float] = None            # segundos de mídia, para calcular o progresso
    runner: Optional[Callable[["Job", "JobContext"], None]] = None
    extra: dict[str, Any] = field(default_factory=dict)   # dados livres da ferramenta (ex.: perfil usado)

    # --- estado (alterado só pelo TaskManager) ---
    id: int = field(default_factory=lambda: next(_job_ids))
    state: TaskState = TaskState.WAITING
    progress: float = 0.0                       # 0.0–1.0
    indeterminate: bool = False                 # True quando a duração é desconhecida
    message: str = "Aguardando na fila"
    detail: str = ""                            # detalhe técnico do erro (para "ver detalhes")
    speed: Optional[float] = None
    input_size: Optional[int] = None
    output_size: Optional[int] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def elapsed(self) -> float:
        """Tempo decorrido em segundos (para tarefas em espera, 0)."""
        if self.started_at is None:
            return 0.0
        return (self.finished_at or time.time()) - self.started_at

    @property
    def is_finished(self) -> bool:
        return self.state in FINISHED_STATES

    @property
    def state_label(self) -> str:
        return STATE_LABELS[self.state]


class JobContext:
    """Ferramentas entregues ao runner de um job."""

    def __init__(self, manager: "TaskManager", job: Job):
        self._manager = manager
        self.job = job

    @property
    def cancelled(self) -> bool:
        return self.job.cancel_event.is_set()

    def check_cancelled(self) -> None:
        if self.cancelled:
            raise JobCancelled()

    def set_message(self, text: str) -> None:
        self.job.message = text
        self._manager._emit_update(self.job, force=True)

    def set_progress(self, fraction: float, message: Optional[str] = None) -> None:
        self.job.progress = max(0.0, min(1.0, fraction))
        if message is not None:
            self.job.message = message
        self._manager._emit_update(self.job)

    def run_ffmpeg(self, args: list[str], duration: Optional[float] = None,
                   span: tuple[float, float] = (0.0, 1.0)) -> FFmpegResult:
        """Executa o FFmpeg dentro do job.

        ``span`` mapeia o progresso desta etapa para uma faixa do progresso total
        (útil em operações de várias etapas). Levanta JobCancelled / JobError.
        """
        start, end = span
        job = self.job

        def on_progress(p: Progress) -> None:
            job.speed = p.speed
            if p.fraction is None:
                job.indeterminate = True
                job.message = f"Processando… {p.out_time:.0f}s de mídia"
            else:
                job.indeterminate = False
                job.progress = start + (end - start) * p.fraction
                job.message = f"Processando… {p.fraction * 100:.0f}%" + (
                    f" · {p.speed:.1f}x" if p.speed else "")
            self._manager._emit_update(job)

        try:
            result = run_ffmpeg(args, ffmpeg_path=self._manager.ffmpeg_path, duration=duration,
                                on_progress=on_progress, cancel_event=job.cancel_event)
        except FFmpegError as exc:
            raise JobError(str(exc), str(exc)) from exc
        if result.cancelled:
            raise JobCancelled()
        if result.returncode != 0:
            raise JobError(friendly_error(result.stderr_tail), result.stderr_tail)
        return result


class TaskManager:
    """Fila de tarefas com limite de execuções simultâneas."""

    def __init__(self, max_concurrent: int = 1, ffmpeg_path: str = "ffmpeg"):
        self.ffmpeg_path = ffmpeg_path
        self._max_concurrent = max(1, max_concurrent)
        self._lock = threading.RLock()
        self._jobs: list[Job] = []
        self._events: "queue.Queue[tuple[str, Job]]" = queue.Queue()
        self._listeners: list[Callable[[str, Job], None]] = []
        self._threads: dict[int, threading.Thread] = {}
        self._last_emit: dict[int, float] = {}

    # ------------------------------------------------------------------ API pública
    @property
    def jobs(self) -> list[Job]:
        with self._lock:
            return list(self._jobs)

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    def set_max_concurrent(self, value: int) -> None:
        with self._lock:
            self._max_concurrent = max(1, value)
        self._schedule()

    def subscribe(self, listener: Callable[[str, Job], None]) -> Callable[[], None]:
        """Registra um listener (chamado na thread do Tkinter via pump). Devolve a função de cancelar."""
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)
        return unsubscribe

    def add(self, job: Job) -> Job:
        job.input_size = file_size(job.input_path)
        job.state = TaskState.WAITING
        with self._lock:
            self._jobs.append(job)
        self._events.put(("added", job))
        self._schedule()
        return job

    def add_many(self, jobs: list[Job]) -> list[Job]:
        return [self.add(j) for j in jobs]

    def cancel(self, job_id: int) -> None:
        with self._lock:
            job = next((j for j in self._jobs if j.id == job_id), None)
            if not job or job.is_finished:
                return
            job.cancel_event.set()
            if job.state == TaskState.WAITING:       # ainda não começou: cancela na hora
                self._finish(job, TaskState.CANCELLED, "Cancelado pelo usuário")

    def cancel_all(self) -> None:
        for job in self.jobs:
            self.cancel(job.id)

    def remove(self, job_id: int) -> None:
        """Tira uma tarefa já finalizada da lista (tarefas ativas não podem ser removidas)."""
        with self._lock:
            job = next((j for j in self._jobs if j.id == job_id and j.is_finished), None)
            if job:
                self._jobs.remove(job)
                self._last_emit.pop(job.id, None)
        if job:
            self._events.put(("removed", job))

    def clear_finished(self) -> None:
        for job in self.jobs:
            if job.is_finished:
                self.remove(job.id)

    def counts(self) -> dict[str, int]:
        with self._lock:
            result = {s.value: 0 for s in TaskState}
            for j in self._jobs:
                result[j.state.value] += 1
            return result

    @property
    def active_count(self) -> int:
        """Tarefas aguardando ou em execução."""
        c = self.counts()
        return c["waiting"] + c["running"]

    def pump(self) -> int:
        """Entrega os eventos pendentes aos listeners. Chame na thread do Tkinter (ex.: a cada 100 ms)."""
        delivered = 0
        while True:
            try:
                event, job = self._events.get_nowait()
            except queue.Empty:
                break
            with self._lock:
                listeners = list(self._listeners)
            for listener in listeners:
                try:
                    listener(event, job)
                except Exception:       # um listener com defeito não pode derrubar os demais
                    traceback.print_exc()
            delivered += 1
        return delivered

    def shutdown(self, timeout: float = 8.0) -> None:
        """Cancela tudo e espera os processos do FFmpeg encerrarem (ao fechar o programa)."""
        self.cancel_all()
        deadline = time.time() + timeout
        for thread in list(self._threads.values()):
            thread.join(max(0.0, deadline - time.time()))

    # ------------------------------------------------------------------ internos
    def _schedule(self) -> None:
        """Inicia jobs em espera enquanto houver vaga."""
        with self._lock:
            running = sum(1 for j in self._jobs if j.state == TaskState.RUNNING)
            for job in self._jobs:
                if running >= self._max_concurrent:
                    break
                if job.state != TaskState.WAITING:
                    continue
                job.state = TaskState.RUNNING          # marca já aqui para não iniciar duas vezes
                job.started_at = time.time()
                job.message = "Iniciando…"
                running += 1
                thread = threading.Thread(target=self._worker, args=(job,), daemon=True,
                                          name=f"job-{job.id}")
                self._threads[job.id] = thread
                self._events.put(("updated", job))
                thread.start()

    def _worker(self, job: Job) -> None:
        ctx = JobContext(self, job)
        try:
            ctx.check_cancelled()
            if job.runner:
                job.runner(job, ctx)
            elif job.ffmpeg_args:
                ctx.run_ffmpeg(job.ffmpeg_args, duration=job.duration)
            else:
                raise JobError("Tarefa sem comando para executar.")
            ctx.check_cancelled()
            if job.output_path and not file_size(job.output_path):
                raise JobError("O arquivo de saída não foi gerado.")
            job.progress = 1.0
            job.indeterminate = False
            job.output_size = file_size(job.output_path)
            # Um runner pode definir ``extra["done_message"]`` (ex.: "12 imagens salvas").
            self._finish(job, TaskState.DONE, job.extra.get("done_message", "Concluído"))
        except JobCancelled:
            self._cleanup(job)
            self._finish(job, TaskState.CANCELLED, "Cancelado pelo usuário")
        except JobError as exc:
            self._cleanup(job)
            job.detail = exc.detail
            self._finish(job, TaskState.ERROR, exc.message)
        except Exception as exc:                       # erro de programação: registrar o rastreio
            self._cleanup(job)
            job.detail = traceback.format_exc()
            self._finish(job, TaskState.ERROR, f"Erro inesperado: {exc}")

    @staticmethod
    def _cleanup(job: Job) -> None:
        """Apaga o que a tarefa deixou pela metade: o arquivo de saída e/ou a pasta ``extra['cleanup_dir']``."""
        remove_quietly(job.output_path)
        folder = job.extra.get("cleanup_dir")
        if folder:
            shutil.rmtree(folder, ignore_errors=True)

    def _finish(self, job: Job, state: TaskState, message: str) -> None:
        with self._lock:
            job.state = state
            job.message = message
            job.finished_at = time.time()
            if job.started_at is None:
                job.started_at = job.finished_at
        release_path(job.output_path)                  # o nome de saída volta a ficar disponível
        release_path(job.extra.get("open_path"))       # idem para a pasta de saída, se houver
        self._events.put(("finished", job))
        self._threads.pop(job.id, None)
        self._schedule()

    def _emit_update(self, job: Job, force: bool = False) -> None:
        """Publica um evento 'updated' no máximo ~10 vezes por segundo por job."""
        now = time.time()
        if not force and now - self._last_emit.get(job.id, 0.0) < 0.1:
            return
        self._last_emit[job.id] = now
        self._events.put(("updated", job))
