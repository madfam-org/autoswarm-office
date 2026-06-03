"""
Track E2: ACP stdio / JSON-RPC server stub
Mirrors Hermes' acp_adapter/ — exposes Selva as an editor-native agent
over stdio (VS Code / Zed / JetBrains Agent Protocol).

Start with: python -m nexus_api.acp_server
Protocol: newline-delimited JSON-RPC 2.0 over stdin/stdout
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

SERVER_NAME = "selva-office"
SERVER_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------


def _response(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _write(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Method handlers
# ---------------------------------------------------------------------------


async def handle_initialize(params: dict, req_id: Any) -> None:
    _write(
        _response(
            req_id,
            {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
                "capabilities": {
                    "run_acp": True,
                    "get_result": True,
                    "list_skills": True,
                },
                "started_at": datetime.now(tz=UTC).isoformat(),
            },
        )
    )


async def handle_run_acp(params: dict, req_id: Any) -> None:
    target_url: str = params.get("target_url", "")
    workspace_path: str = params.get("workspace_path", os.getcwd())
    if not target_url:
        _write(_error(req_id, -32602, "target_url is required"))
        return
    try:
        from nexus_api.tasks.acp_tasks import run_acp_workflow_task

        task = run_acp_workflow_task.delay(
            target_url,
            metadata={"workspace_path": workspace_path, "source": "acp_server"},
        )
        _write(_response(req_id, {"run_id": task.id, "status": "dispatched"}))
    except ImportError:
        # Return a stub run_id when running outside nexus-api context
        import uuid

        stub_id = str(uuid.uuid4())
        logger.warning("ACP server: nexus_api not available — returning stub run_id %s", stub_id)
        _write(_response(req_id, {"run_id": stub_id, "status": "stub_mode"}))
    except Exception as exc:
        _write(_error(req_id, -32603, str(exc)))


async def handle_get_result(params: dict, req_id: Any) -> None:
    run_id: str = params.get("run_id", "")
    if not run_id:
        _write(_error(req_id, -32602, "run_id is required"))
        return
    try:
        from celery.result import AsyncResult

        result = AsyncResult(run_id)
        state = result.state
        output = result.result if result.ready() else None
        _write(_response(req_id, {"run_id": run_id, "status": state, "output": output}))
    except ImportError:
        _write(_response(req_id, {"run_id": run_id, "status": "unknown", "output": None}))
    except Exception as exc:
        _write(_error(req_id, -32603, str(exc)))


async def handle_list_skills(params: dict, req_id: Any) -> None:
    try:
        from selva_skills import get_skill_registry

        skills = [
            {"name": s.name, "description": s.description}
            for s in get_skill_registry().list_skills()
        ]
        _write(_response(req_id, {"skills": skills}))
    except Exception as exc:
        _write(_error(req_id, -32603, str(exc)))


_HANDLERS = {
    "initialize": handle_initialize,
    "run_acp": handle_run_acp,
    "get_result": handle_get_result,
    "list_skills": handle_list_skills,
}


# ---------------------------------------------------------------------------
# Main server loop
# ---------------------------------------------------------------------------


async def serve() -> None:
    logger.info("ACP server starting (stdio JSON-RPC)…")
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        line = await reader.readline()
        if not line:
            break
        try:
            request = json.loads(line.decode().strip())
        except json.JSONDecodeError as exc:
            _write(_error(None, -32700, f"Parse error: {exc}"))
            continue

        method = request.get("method", "")
        params = request.get("params", {})
        req_id = request.get("id")

        handler = _HANDLERS.get(method)
        if handler is None:
            _write(_error(req_id, -32601, f"Method not found: {method}"))
            continue

        try:
            await handler(params, req_id)
        except Exception as exc:
            logger.exception("ACP server: unhandled error in %s", method)
            _write(_error(req_id, -32603, str(exc)))


def main() -> None:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    asyncio.run(serve())


if __name__ == "__main__":
    main()
