from __future__ import annotations

from types import SimpleNamespace

from runtime.api.conversations import _active_persisted_run_id_for_conversation


class FakeRuns:
    def __init__(self, runs):
        self._runs = runs

    def list(self, *, conversation_id: str):
        return [
            run
            for run in self._runs
            if getattr(run, "conversation_id", "") == conversation_id
        ]


def test_active_persisted_run_detects_running_conversation_run() -> None:
    runtime = SimpleNamespace(runs=FakeRuns([
        SimpleNamespace(id="done-run", conversation_id="conv-1", status="success"),
        SimpleNamespace(id="active-run", conversation_id="conv-1", status="running"),
    ]))

    assert _active_persisted_run_id_for_conversation(runtime, "conv-1") == "active-run"


def test_active_persisted_run_ignores_finished_runs() -> None:
    runtime = SimpleNamespace(runs=FakeRuns([
        SimpleNamespace(id="done-run", conversation_id="conv-1", status="success"),
        SimpleNamespace(id="failed-run", conversation_id="conv-1", status="failure"),
    ]))

    assert _active_persisted_run_id_for_conversation(runtime, "conv-1") == ""


def test_active_persisted_run_tolerates_repository_errors() -> None:
    runtime = SimpleNamespace(runs=SimpleNamespace(list=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom"))))

    assert _active_persisted_run_id_for_conversation(runtime, "conv-1") == ""
