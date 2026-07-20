from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from providers.desktop_observation import DesktopObservationService, build_desktop_state
from runtime.core.capability import normalize_provider_kind
from runtime.security import PathGuard
from runtime.skills import register_builtin_tools
from runtime.skills.desktop import capture_screen, register_desktop_tools
from runtime.tool_registry import ToolRegistry


def test_desktop_state_contract_records_counts() -> None:
    state = build_desktop_state(
        platform_name="Windows",
        scope="windows",
        windows=[{"window_id": "1", "title": "Demo"}],
        active_window={"window_id": "1", "title": "Demo"},
        processes=[{"process_id": 10, "name": "demo.exe"}],
        diagnostics=[{"code": "demo", "message": "ok"}],
        captured_at="2026-07-20T00:00:00Z",
    )

    assert state["schema_version"] == "desktop_state.v1"
    assert state["kind"] == "desktop_state"
    assert state["source"] == "desktop_observation"
    assert state["counts"] == {"windows": 1, "processes": 1, "diagnostics": 1}
    assert state["active_window"]["title"] == "Demo"


def test_desktop_provider_degrades_window_observation_off_windows() -> None:
    service = DesktopObservationService(platform_name="Linux")

    readiness = service.readiness()
    state = service.list_windows()

    assert readiness["health"] == "degraded"
    assert state["windows"] == []
    assert state["diagnostics"][0]["code"] == "window_observation_unsupported"


def test_register_desktop_tools_exposes_independent_provider_metadata() -> None:
    registry = ToolRegistry()
    register_desktop_tools(registry)

    ids = {item["id"] for item in registry.list_specs()}
    screen = registry.get_public_spec("desktop.capture_screen")
    windows = registry.get_public_spec("desktop.list_windows")

    assert ids == {
        "desktop.list_windows",
        "desktop.active_window",
        "desktop.list_processes",
        "desktop.capture_screen",
        "desktop.capture_window",
    }
    assert normalize_provider_kind("desktop_observation") == "desktop"
    assert windows["capability"] == "desktop.observation"
    assert windows["provider_kind"] == "desktop"
    assert windows["provider"]["lifecycle"] == "local_observer"
    assert windows["artifacts"] == ["desktop_state"]
    assert windows["requires_confirmation"] is False
    assert screen["artifacts"] == ["screenshot", "visual_evidence", "desktop_state"]
    assert screen["effects"] == ["artifact_write"]
    assert screen["requires_confirmation"] is True


def test_builtin_registration_includes_desktop_group() -> None:
    registry = ToolRegistry()
    register_builtin_tools(registry)

    assert registry.get_public_spec("desktop.list_windows")["capability"] == "desktop.observation"


def test_capture_screen_uses_task_temp_and_returns_visual_evidence(monkeypatch, tmp_path: Path) -> None:
    class FakeService:
        def capture_screen(self, *, output_path: Path, format: str) -> dict:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"fake image")
            return {
                "type": "desktop_observation",
                "source_type": "desktop_screen",
                "path": str(output_path),
                "format": format,
                "size": output_path.stat().st_size,
                "width": 10,
                "height": 5,
                "artifact_kind": "screenshot",
                "artifacts": ["screenshot", "visual_evidence", "desktop_state"],
                "effects": ["artifact_write"],
                "roles": ["evidence", "verification"],
                "verification_strength": "standard",
                "desktop_state": {"schema_version": "desktop_state.v1", "kind": "desktop_state"},
                "visual_evidence": {"schema_version": "visual_evidence.v1", "kind": "visual_evidence"},
            }

    monkeypatch.setattr("runtime.skills.desktop._service", lambda: FakeService())
    context = SimpleNamespace(
        temp_dir=tmp_path / "task-artifacts",
        path_guard=PathGuard([tmp_path]),
        log=lambda *_args, **_kwargs: None,
    )

    import asyncio

    result = asyncio.run(capture_screen({}, context))

    assert Path(result["path"]).parent == tmp_path / "task-artifacts" / "desktop"
    assert result["artifact_kind"] == "screenshot"
    assert result["artifacts"] == ["screenshot", "visual_evidence", "desktop_state"]

