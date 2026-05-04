"""
Gap 6: Trajectories REST router — ShareGPT format exports.
"""

from __future__ import annotations

import io
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from selva_workflows.trajectory import TrajectoryExporter

from ..auth import CurrentUser, require_roles

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/trajectories", tags=["Trajectories"])

_exporter = TrajectoryExporter()


class TrajectoryResponse(BaseModel):
    id: str
    conversations: list[dict]


class BatchExportRequest(BaseModel):
    run_ids: list[str]
    format: str = "sharegpt"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[str])
async def list_trajectories(
    user: CurrentUser = Depends(require_roles(["admin", "enterprise-cleanroom"])),
) -> list[str]:
    """List all exportable ACP run IDs."""
    return _exporter.list_exportable_runs()


@router.get("/{run_id}", response_model=TrajectoryResponse)
async def get_trajectory(
    run_id: str,
    user: CurrentUser = Depends(require_roles(["admin", "enterprise-cleanroom"])),
) -> TrajectoryResponse:
    """Return a single ShareGPT-format trajectory for *run_id*."""
    traj = _exporter.build_sharegpt(run_id)
    if not traj["conversations"]:
        raise HTTPException(status_code=404, detail=f"No transcript found for run_id={run_id}")
    return TrajectoryResponse(id=traj["id"], conversations=traj["conversations"])


@router.post("/batch")
async def export_batch(
    req: BatchExportRequest,
    user: CurrentUser = Depends(require_roles(["admin", "enterprise-cleanroom"])),
) -> StreamingResponse:
    """
    Export multiple trajectories as a JSONL file download.

    Body: {"run_ids": ["abc", "def"], "format": "sharegpt"}
    """
    if req.format != "sharegpt":
        raise HTTPException(status_code=400, detail=f"Unsupported format: {req.format}")

    lines: list[str] = []
    for run_id in req.run_ids:
        traj = _exporter.build_sharegpt(run_id)
        if traj["conversations"]:
            lines.append(json.dumps(traj, ensure_ascii=False))

    content = "\n".join(lines) + "\n"
    filename = f"trajectories_{len(lines)}_runs.jsonl"

    return StreamingResponse(
        content=io.StringIO(content),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
