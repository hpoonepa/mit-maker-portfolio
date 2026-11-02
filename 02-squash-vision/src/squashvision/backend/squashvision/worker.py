from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from threading import Event, Thread
from typing import Protocol
from uuid import uuid4

from squashvision.jobs import (
    ClaimLostError,
    HEARTBEAT_INTERVAL,
    JobQueue,
    PlannedChunk,
    TimeRange,
)
from squashvision.models import AnalysisJob, JobStatus, Stage

HeartbeatWait = Callable[[Event, float], bool]
_FAILURE_CODE = re.compile(r"[a-z][a-z0-9_]{0,99}\Z")


def _typed_failure_code(error: BaseException) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and _FAILURE_CODE.fullmatch(code) is not None:
        return code
    return "worker_runtime_error"




class AnalysisHandler(Protocol):
    def plan(self, job: AnalysisJob) -> Iterable[PlannedChunk]: ...

    def run(
        self,
        job: AnalysisJob,
        stage: Stage,
        chunk: TimeRange,
        artifact: Path,
    ) -> Path: ...


class Worker:
    def __init__(
        self,
        queue: JobQueue,
        worker_id: str,
        handler: AnalysisHandler,
        *,
        clock: Callable[[], datetime] | None = None,
        heartbeat_wait: HeartbeatWait | None = None,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id must not be empty")
        self.queue = queue
        self.worker_id = worker_id
        self.handler = handler
        self.clock = clock or queue.clock
        self._heartbeat_wait = heartbeat_wait or self._wait_for_stop
        self._job_id: str | None = None
        self._claim_token: str | None = None

    def run_once(self) -> bool:
        try:
            return self._run_once()
        except ClaimLostError:
            self._clear_claim()
            raise

    def _run_once(self) -> bool:
        if self._job_id is None:
            self.queue.heartbeat(self.worker_id)
            claimed = self.queue.claim(self.worker_id)
            if claimed is None:
                return False
            if claimed.claim_token is None:
                raise RuntimeError("claimed job did not receive a claim token")
            self._job_id = claimed.public_id
            self._claim_token = claimed.claim_token

        job_id, claim_token = self._active_claim()
        stop = Event()
        lease_errors: list[BaseException] = []

        def maintain_lease() -> None:
            while not self._heartbeat_wait(
                stop, HEARTBEAT_INTERVAL.total_seconds()
            ):
                try:
                    self.queue.heartbeat_claim(
                        job_id, self.worker_id, claim_token
                    )
                except BaseException as error:
                    lease_errors.append(error)
                    return

        def raise_if_lease_lost() -> None:
            if lease_errors:
                raise lease_errors[0]

        keeper = Thread(
            target=maintain_lease,
            name=f"squashvision-heartbeat-{self.worker_id}",
            daemon=True,
        )
        keeper.start()
        try:
            self.queue.heartbeat_claim(job_id, self.worker_id, claim_token)
            job = self.queue.apply_requested_control_claimed(
                job_id, self.worker_id, claim_token
            )
            if job.status is not JobStatus.RUNNING:
                self._clear_claim()
                return True

            try:
                planned = tuple(self.handler.plan(job))
                raise_if_lease_lost()
                if not self.queue.has_plan(job.public_id):
                    self.queue.plan_claimed(
                        job.public_id,
                        self.worker_id,
                        claim_token,
                        planned,
                    )
                else:
                    self.queue.reconcile_plan_claimed(
                        job.public_id,
                        self.worker_id,
                        claim_token,
                        planned,
                    )
                raise_if_lease_lost()
            except BaseException as error:
                if lease_errors:
                    raise lease_errors[0] from error
                self._fail_owned(job.public_id, claim_token, error)

            chunk = self.queue.next_chunk(job.public_id)
            raise_if_lease_lost()
            if chunk is None:
                self.queue.complete_claimed(
                    job.public_id, self.worker_id, claim_token
                )
                self._clear_claim()
                return True

            try:
                contract_builder = getattr(
                    self.handler, "chunk_contract", None
                )
                if callable(contract_builder):
                    exact = contract_builder(
                        job, chunk.stage, chunk.time_range
                    )
                    raise_if_lease_lost()
                    if not isinstance(exact, PlannedChunk):
                        raise TypeError(
                            "analysis handler chunk_contract must return PlannedChunk"
                        )
                    self.queue.reconcile_chunk_claimed(
                        job.public_id,
                        self.worker_id,
                        claim_token,
                        exact,
                    )
                raise_if_lease_lost()
            except BaseException as error:
                if lease_errors:
                    raise lease_errors[0] from error
                self._fail_owned(job.public_id, claim_token, error)

            self.queue.start_chunk_claimed(
                job.public_id,
                chunk.stage,
                chunk.time_range,
                self.worker_id,
                claim_token,
            )
            work_dir = self.queue.storage.root / ".worker" / job.public_id
            work_dir.mkdir(parents=True, exist_ok=True)
            proposed = work_dir / f"{uuid4().hex}.artifact"
            try:
                artifact = self.handler.run(
                    job, chunk.stage, chunk.time_range, proposed
                )
                raise_if_lease_lost()
                self.queue.checkpoint_claimed(
                    job.public_id,
                    chunk.stage,
                    chunk.time_range,
                    artifact,
                    self.worker_id,
                    claim_token,
                )
                raise_if_lease_lost()
            except BaseException as error:
                self._clear_claim()
                if lease_errors:
                    raise lease_errors[0] from error
                if isinstance(error, ClaimLostError):
                    raise
                try:
                    self.queue.fail_claimed(
                        job.public_id,
                        self.worker_id,
                        claim_token,
                        str(error),
                        failure_code=_typed_failure_code(error),
                    )
                except ClaimLostError as lost:
                    raise lost from error
                raise
            finally:
                proposed.unlink(missing_ok=True)

            bounded = self.queue.apply_requested_control_claimed(
                job.public_id, self.worker_id, claim_token
            )
            raise_if_lease_lost()
            if bounded.status is not JobStatus.RUNNING:
                self._clear_claim()
            return True
        finally:
            stop.set()
            keeper.join()

    def _fail_owned(
        self, job_id: str, claim_token: str, error: BaseException
    ) -> None:
        self._clear_claim()
        if isinstance(error, ClaimLostError):
            raise error
        try:
            self.queue.fail_claimed(
                job_id,
                self.worker_id,
                claim_token,
                str(error),
                failure_code=_typed_failure_code(error),
            )
        except ClaimLostError as lost:
            raise lost from error
        raise error

    def _active_claim(self) -> tuple[str, str]:
        if self._job_id is None or self._claim_token is None:
            raise RuntimeError("worker has no active claim")
        return self._job_id, self._claim_token

    def _clear_claim(self) -> None:
        self._job_id = None
        self._claim_token = None

    @staticmethod
    def _wait_for_stop(stop: Event, seconds: float) -> bool:
        return stop.wait(seconds)
