from __future__ import annotations

import base64
import re
import shutil
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from runtime.core.capability_pack import (
    CAPABILITY_PACK_KINDS,
    CAPABILITY_PACK_SOURCES,
    CAPABILITY_PACK_STATES,
    CapabilityPack,
    CapabilityPackEntry,
    CapabilityPackPermissions,
    CapabilityPackProvenance,
    capability_pack_export_bundle,
)
from runtime.persistence import AtomicJsonDocumentStorage, DocumentStorage
from runtime.run_store import utc_now


CAPABILITY_PACK_STORE_SCHEMA_VERSION = "capability_pack_store.v1"
MAX_EXPORT_FILE_COUNT = 64
MAX_EXPORT_TOTAL_BYTES = 2_000_000
VALID_ENTRY_KINDS = {"instructions", "runbook", "context", "command", "mcp", "http"}
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")


class CapabilityPackStore:
    """全局用户数据级 Capability Pack 的存储库。"""

    def __init__(
        self,
        root_path: Path,
        *,
        storage: DocumentStorage | None = None,
    ) -> None:
        self.root_path = root_path
        self.items_path = root_path / "items"
        self.exports_path = root_path / "exports"
        self._storage = storage if storage is not None else AtomicJsonDocumentStorage(root_path / "index.json")
        self.store_path = self._storage.path
        self._packs: dict[str, CapabilityPack] = {}
        self.root_path.mkdir(parents=True, exist_ok=True)
        self.items_path.mkdir(parents=True, exist_ok=True)
        self.exports_path.mkdir(parents=True, exist_ok=True)
        self._load()

    def list(self, *, include_archived: bool = False) -> list[CapabilityPack]:
        items = list(self._packs.values())
        if not include_archived:
            items = [item for item in items if item.state != "archived"]
        return sorted(items, key=lambda item: item.updated_at or item.created_at, reverse=True)

    def get(self, pack_id: str) -> CapabilityPack | None:
        return self._packs.get(pack_id)

    def item_path(self, pack_id: str) -> Path:
        return self.items_path / pack_id

    def create(self, payload: dict[str, Any]) -> CapabilityPack:
        now = utc_now()
        pack_id = _unique_pack_id(
            _safe_pack_id(payload.get("id")) or _slug_from_name(payload.get("name")) or f"pack-{uuid4().hex[:8]}",
            set(self._packs),
        )
        pack = _pack_from_payload(payload, pack_id=pack_id, created_at=now, updated_at=now)
        self._write_payload_files(pack.id, payload.get("files"))
        self._packs[pack.id] = pack
        self._save()
        return pack

    def update(self, pack_id: str, payload: dict[str, Any]) -> CapabilityPack:
        current = self._require(pack_id)
        merged = current.to_dict()
        _deep_update(merged, payload)
        updated = _pack_from_payload(
            merged,
            pack_id=current.id,
            created_at=current.created_at,
            updated_at=utc_now(),
        )
        self._write_payload_files(pack_id, payload.get("files"))
        self._packs[pack_id] = updated
        self._save()
        return updated

    def set_state(self, pack_id: str, state: str) -> CapabilityPack:
        current = self._require(pack_id)
        normalized = _normalize_choice(state, CAPABILITY_PACK_STATES, current.state)
        updated = replace(current, state=normalized, updated_at=utc_now())
        self._packs[pack_id] = updated
        self._save()
        return updated

    def delete(self, pack_id: str) -> bool:
        if pack_id not in self._packs:
            return False
        del self._packs[pack_id]
        path = self.item_path(pack_id)
        if _path_under(path, self.items_path) and path.exists():
            shutil.rmtree(path)
        self._save()
        return True

    def export_bundle(self, pack_id: str) -> dict[str, Any]:
        pack = self._require(pack_id)
        if not pack.exportable:
            raise PermissionError("capability pack is not exportable")
        files, skipped = self._export_files(pack_id)
        return capability_pack_export_bundle(
            pack,
            exported_at=utc_now(),
            files=tuple(files),
            skipped_files=tuple(skipped),
        )

    def _require(self, pack_id: str) -> CapabilityPack:
        pack = self.get(pack_id)
        if not pack:
            raise KeyError(f"unknown capability pack: {pack_id}")
        return pack

    def _load(self) -> None:
        value = self._storage.load()
        items = value.get("capability_packs") if isinstance(value, dict) else []
        if not isinstance(items, list):
            return
        for item in items:
            if isinstance(item, dict):
                pack = _pack_from_payload(item)
                self._packs[pack.id] = pack

    def _save(self) -> None:
        self._storage.save({
            "schema_version": CAPABILITY_PACK_STORE_SCHEMA_VERSION,
            "capability_packs": [item.to_dict() for item in self._packs.values()],
        })

    def _write_payload_files(self, pack_id: str, files: Any) -> None:
        if not isinstance(files, dict):
            return
        root = self.item_path(pack_id).resolve()
        root.mkdir(parents=True, exist_ok=True)
        for raw_path, value in files.items():
            relative_path = _safe_relative_file_path(raw_path)
            target = (root / relative_path).resolve()
            if not _path_under(target, root):
                raise ValueError(f"unsafe capability pack file path: {raw_path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(value), encoding="utf-8")

    def _export_files(self, pack_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        root = self.item_path(pack_id)
        if not root.exists():
            return [], []

        files: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        total = 0
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if len(files) >= MAX_EXPORT_FILE_COUNT:
                skipped.append({"path": relative, "reason": "file_count_limit"})
                continue
            try:
                data = path.read_bytes()
            except OSError as exc:
                skipped.append({"path": relative, "reason": f"read_failed: {exc}"})
                continue
            if total + len(data) > MAX_EXPORT_TOTAL_BYTES:
                skipped.append({"path": relative, "reason": "total_size_limit", "bytes": len(data)})
                continue
            total += len(data)
            item: dict[str, Any] = {"path": relative, "bytes": len(data)}
            try:
                item["encoding"] = "utf-8"
                item["content"] = data.decode("utf-8")
            except UnicodeDecodeError:
                item["encoding"] = "base64"
                item["content_base64"] = base64.b64encode(data).decode("ascii")
            files.append(item)
        return files, skipped


def _pack_from_payload(
    payload: dict[str, Any],
    *,
    pack_id: str | None = None,
    created_at: str | None = None,
    updated_at: str | None = None,
) -> CapabilityPack:
    normalized_id = _safe_pack_id(pack_id or payload.get("id")) or f"pack-{uuid4().hex[:8]}"
    name = str(payload.get("name") or normalized_id).strip() or normalized_id
    now = utc_now()
    return CapabilityPack(
        id=normalized_id,
        name=name,
        kind=_normalize_choice(payload.get("kind"), CAPABILITY_PACK_KINDS, "method_skill"),  # type: ignore[arg-type]
        state=_normalize_choice(payload.get("state"), CAPABILITY_PACK_STATES, "draft"),  # type: ignore[arg-type]
        source=_normalize_choice(payload.get("source"), CAPABILITY_PACK_SOURCES, "ai_generated"),  # type: ignore[arg-type]
        version=str(payload.get("version") or "0.1.0"),
        description=str(payload.get("description") or ""),
        summary=str(payload.get("summary") or ""),
        instructions=str(payload.get("instructions") or ""),
        tags=tuple(_string_list(payload.get("tags"))),
        entry=_entry_from_payload(payload.get("entry")),
        permissions=_permissions_from_payload(payload.get("permissions")),
        provenance=_provenance_from_payload(payload.get("provenance")),
        tests=tuple(_dict_list(payload.get("tests"))),
        exportable=bool(payload.get("exportable", True)),
        created_at=str(created_at or payload.get("created_at") or now),
        updated_at=str(updated_at or payload.get("updated_at") or now),
        metadata=_dict(payload.get("metadata")),
    )


def _entry_from_payload(value: Any) -> CapabilityPackEntry:
    payload = value if isinstance(value, dict) else {}
    return CapabilityPackEntry(
        kind=_normalize_choice(payload.get("kind"), VALID_ENTRY_KINDS, "instructions"),  # type: ignore[arg-type]
        main=str(payload.get("main") or "SKILL.md"),
        command=str(payload.get("command") or ""),
        args=tuple(_string_list(payload.get("args"))),
        metadata=_dict(payload.get("metadata")),
    )


def _permissions_from_payload(value: Any) -> CapabilityPackPermissions:
    payload = value if isinstance(value, dict) else {}
    return CapabilityPackPermissions(
        filesystem=str(payload.get("filesystem") or "none"),
        shell=str(payload.get("shell") or "false"),
        network=str(payload.get("network") or "false"),
        model=str(payload.get("model") or "false"),
        external_apps=tuple(_string_list(payload.get("external_apps"))),
        notes=str(payload.get("notes") or ""),
    )


def _provenance_from_payload(value: Any) -> CapabilityPackProvenance:
    payload = value if isinstance(value, dict) else {}
    return CapabilityPackProvenance(
        source_run_id=str(payload.get("source_run_id") or ""),
        source_task_id=str(payload.get("source_task_id") or ""),
        source_conversation_id=str(payload.get("source_conversation_id") or ""),
        model=str(payload.get("model") or ""),
        created_by=str(payload.get("created_by") or "ai"),
        notes=str(payload.get("notes") or ""),
    )


def _safe_pack_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text if SAFE_ID_RE.match(text) else ""


def _slug_from_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff_.-]+", "-", text)
    text = text.strip("-_.")
    return text[:80] if text else ""


def _unique_pack_id(base: str, existing: set[str]) -> str:
    if base not in existing:
        return base
    suffix = uuid4().hex[:8]
    trimmed = base[: max(1, 80 - len(suffix) - 1)]
    return f"{trimmed}-{suffix}"


def _safe_relative_file_path(raw_path: Any) -> Path:
    text = str(raw_path or "").strip().replace("\\", "/")
    posix = PurePosixPath(text)
    if not text or posix.is_absolute() or any(part in {"", ".", ".."} for part in posix.parts):
        raise ValueError(f"unsafe capability pack file path: {raw_path}")
    return Path(*posix.parts)


def _path_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _normalize_choice(value: Any, allowed: frozenset[str] | set[str], fallback: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else fallback


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _deep_update(target: dict[str, Any], payload: dict[str, Any]) -> None:
    for key, value in payload.items():
        if key == "id":
            continue
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value
