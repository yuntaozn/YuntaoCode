from __future__ import annotations

import argparse
import json
import secrets
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tornado.ioloop
import tornado.web

from .api.backend import BackendLoginHandler
from .api.attachments import AttachmentContentHandler, AttachmentDetailHandler, AttachmentsHandler
from .api.backups import BackupRestoreHandler, BackupsHandler
from .api.conversations import (
    ConversationCompressHandler,
    ConversationConfirmHandler,
    ConversationDetailHandler,
    ConversationGuidanceHandler,
    ConversationMessagesHandler,
    ConversationMessagesStreamHandler,
    ConversationsHandler,
)
from .api.health import HealthHandler
from .api.logs import LogsWebSocketHandler
from .api.memories import MemoriesHandler, MemoryDetailHandler, MemoryPromptHandler
from .api.mcp_services import McpServiceActionHandler, McpServiceDetailHandler, McpServicesHandler
from .api.modes import ModesHandler
from .api.panel import PanelHandler
from .api.plugins import PluginsHandler
from .api.runs import RunDetailHandler, RunEventsStreamHandler, RunsHandler
from .api.settings import SettingsHandler
from .api.tasks import TaskDetailHandler, TasksHandler
from .api.tools import ToolsHandler
from .api.workspaces import WorkspaceDetailHandler, WorkspaceOpenHandler, WorkspacePickerHandler, WorkspacesHandler
from .config import RuntimeConfig
from .conversation_store import ConversationStore
from .backup_store import BackupStore
from .attachment_store import AttachmentStore
from .security import PathGuard
from .settings_store import SettingsStore
from .skills import register_builtin_tools
from .task_runner import TaskRunner
from .task_store import TaskStore
from .tool_registry import ToolRegistry
from .run_store import RunStore
from .run_events import RunEventHub
from .mcp_service_manager import McpServiceManager
from .workspace_store import WorkspaceStore


@dataclass
class RuntimeState:
    config: RuntimeConfig
    registry: ToolRegistry
    store: TaskStore
    runner: TaskRunner
    workspaces: WorkspaceStore
    conversations: ConversationStore
    settings: SettingsStore
    backups: BackupStore
    runs: RunStore
    run_events: RunEventHub
    mcp_services: McpServiceManager
    attachments: AttachmentStore

    def is_tool_available(self, spec: dict[str, Any]) -> bool:
        if spec.get("source_type") != "mcp":
            return True
        return self.mcp_services.is_connected(str(spec.get("source_id") or ""))


def build_runtime(config: RuntimeConfig) -> RuntimeState:
    registry = ToolRegistry()
    register_builtin_tools(registry)
    settings = SettingsStore()
    attachments = AttachmentStore(settings.data_dir / "attachments.db", settings.data_dir / "attachments")
    store = TaskStore(settings.data_dir / "tasks.json")
    path_guard = PathGuard(config.workspace_roots)
    backups = BackupStore(settings.data_dir / "backups", path_guard)
    runner = TaskRunner(
        registry=registry,
        store=store,
        path_guard=path_guard,
        backup_store=backups,
        settings=settings,
        attachment_store=attachments,
    )
    workspaces = WorkspaceStore(config.workspace_roots, path_guard, settings.data_dir / "workspaces.json")
    conversations = ConversationStore(settings.data_dir / "conversations.json")
    runs = RunStore.sqlite(
        settings.data_dir / "runtime.db",
        legacy_store_path=settings.data_dir / "runs.json",
    )
    run_events = RunEventHub(runs)
    mcp_services = McpServiceManager(settings.data_dir / "mcp-services.json", registry=registry)
    return RuntimeState(
        config=config,
        registry=registry,
        store=store,
        runner=runner,
        workspaces=workspaces,
        conversations=conversations,
        settings=settings,
        backups=backups,
        runs=runs,
        run_events=run_events,
        mcp_services=mcp_services,
        attachments=attachments,
    )


def make_app(runtime: RuntimeState) -> tornado.web.Application:
    handler_kwargs: dict[str, Any] = {"runtime": runtime}
    static_path = Path(__file__).parent / "panel" / "static"
    template_path = Path(__file__).parent / "panel" / "templates"
    return tornado.web.Application([
        (r"/", PanelHandler),
        (r"/plugins-page", PanelHandler, {"template_name": "plugins.html", **handler_kwargs}),
        (r"/mcp-services-page", PanelHandler, {"template_name": "mcp-services.html", **handler_kwargs}),
        (r"/settings-page", PanelHandler, {"template_name": "settings.html", **handler_kwargs}),
        (r"/health", HealthHandler, handler_kwargs),
        (r"/settings", SettingsHandler, handler_kwargs),
        (r"/memories/prompt", MemoryPromptHandler, handler_kwargs),
        (r"/memories/([^/]+)", MemoryDetailHandler, handler_kwargs),
        (r"/memories", MemoriesHandler, handler_kwargs),
        (r"/backups/([^/]+)/restore", BackupRestoreHandler, handler_kwargs),
        (r"/backups", BackupsHandler, handler_kwargs),
        (r"/modes", ModesHandler, handler_kwargs),
        (r"/plugins", PluginsHandler, handler_kwargs),
        (r"/mcp-services/([^/]+)/actions", McpServiceActionHandler, handler_kwargs),
        (r"/mcp-services/([^/]+)", McpServiceDetailHandler, handler_kwargs),
        (r"/mcp-services", McpServicesHandler, handler_kwargs),
        (r"/tools", ToolsHandler, handler_kwargs),
        (r"/attachments", AttachmentsHandler, handler_kwargs),
        (r"/attachments/([^/]+)/content", AttachmentContentHandler, handler_kwargs),
        (r"/attachments/([^/]+)", AttachmentDetailHandler, handler_kwargs),
        (r"/backend/login", BackendLoginHandler, handler_kwargs),
        (r"/workspaces/pick", WorkspacePickerHandler, handler_kwargs),
        (r"/workspaces/([^/]+)/open", WorkspaceOpenHandler, handler_kwargs),
        (r"/workspaces/([^/]+)", WorkspaceDetailHandler, handler_kwargs),
        (r"/workspaces", WorkspacesHandler, handler_kwargs),
        (r"/conversations", ConversationsHandler, handler_kwargs),
        (r"/conversations/([^/]+)", ConversationDetailHandler, handler_kwargs),
        (r"/conversations/([^/]+)/guidance", ConversationGuidanceHandler, handler_kwargs),
        (r"/conversations/([^/]+)/messages/stream", ConversationMessagesStreamHandler, handler_kwargs),
        (r"/conversations/([^/]+)/messages", ConversationMessagesHandler, handler_kwargs),
        (r"/conversations/([^/]+)/confirm", ConversationConfirmHandler, handler_kwargs),
        (r"/conversations/([^/]+)/compress", ConversationCompressHandler, handler_kwargs),
        (r"/runs/([^/]+)/events/stream", RunEventsStreamHandler, handler_kwargs),
        (r"/runs/([^/]+)", RunDetailHandler, handler_kwargs),
        (r"/runs", RunsHandler, handler_kwargs),
        (r"/tasks", TasksHandler, handler_kwargs),
        (r"/tasks/([^/]+)", TaskDetailHandler, handler_kwargs),
        (r"/logs/([^/]+)", LogsWebSocketHandler, handler_kwargs),
        (r"/static/(.*)", tornado.web.StaticFileHandler, {"path": str(static_path)}),
    ], template_path=str(template_path), static_path=str(static_path))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local Intelligent Terminal runtime")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", default="")
    parser.add_argument(
        "--workspace",
        action="append",
        default=[],
        help="Allowed workspace root. Can be provided multiple times.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    workspace_roots = args.workspace or [str(Path.cwd())]
    token = args.token or secrets.token_urlsafe(24)
    if args.port == 0:
        args.port = find_free_port(args.host)
    config = RuntimeConfig.build(args.host, args.port, token, workspace_roots)
    runtime = build_runtime(config)
    app = make_app(runtime)
    app.listen(config.port, address=config.host)

    print(json.dumps({
        "event": "ready",
        "url": f"http://{config.host}:{config.port}",
        "workspace_roots": [str(root) for root in runtime.runner.path_guard.workspace_roots],
    }, ensure_ascii=False), flush=True)

    try:
        tornado.ioloop.IOLoop.current().start()
    except KeyboardInterrupt:
        print(json.dumps({"event": "stopped"}, ensure_ascii=False), file=sys.stderr)
    finally:
        try:
            runtime.runs.close()
        finally:
            try:
                runtime.attachments.close()
            finally:
                runtime.mcp_services.close()


def find_free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


if __name__ == "__main__":
    main()
