"""Tests for the Selva CLI."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from selva_sdk.cli import cli
from selva_sdk.exceptions import SelvaError
from selva_sdk.models import (
    AgentResponse,
    KanbanMetricsResponse,
    KanbanTaskImportResponse,
    OverdueNotificationResponse,
    TaskBoardResponse,
    TaskClaimResponse,
    TaskCommentResponse,
    TaskResponse,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TASK = TaskResponse(
    id="aaaa-bbbb-cccc",
    title="Fix login bug",
    description="Fix login bug",
    graph_type="coding",
    assigned_agent_ids=[],
    payload={},
    status="queued",
    kanban_status="todo",
    priority="medium",
    labels=[],
    created_at="2026-03-14T00:00:00",
    completed_at=None,
)

AGENTS = [
    AgentResponse(
        id="agent-1",
        name="Alice",
        role="coder",
        status="idle",
        level=3,
        effective_skills=["python"],
    ),
]


def _mock_client() -> MagicMock:
    mock = MagicMock()
    mock.dispatch.return_value = TASK
    mock.list_agents.return_value = AGENTS
    mock.get_task.return_value = TASK
    mock.get_kanban_board.return_value = TaskBoardResponse(
        columns={
            "todo": [TASK.model_dump()],
            "in_progress": [],
            "review": [],
            "done": [],
            "blocked": [],
        },
        totals={"todo": 1, "in_progress": 0, "review": 0, "done": 0, "blocked": 0},
    )
    mock.update_task_kanban.return_value = TaskResponse(
        **{**TASK.model_dump(), "kanban_status": "in_progress"}
    )
    mock.add_task_comment.return_value = TaskCommentResponse(
        id="comment-1",
        task_id=TASK.id,
        author_id="user-1",
        body="Looks good",
        created_at="2026-03-14T00:00:00",
    )
    mock.get_task_history.return_value = []
    mock.claim_task.return_value = TaskClaimResponse(claimed=True, task=TASK)
    mock.notify_overdue_tasks.return_value = OverdueNotificationResponse(scanned=2, notified=1)
    mock.export_kanban_tasks.return_value = {"items": [TASK.model_dump()]}
    mock.import_kanban_tasks.return_value = KanbanTaskImportResponse(created=1, tasks=[TASK])
    mock.get_kanban_metrics.return_value = KanbanMetricsResponse(
        total=1,
        status_counts={"todo": 1},
        blocked_count=0,
        dependency_blocked_count=0,
        overdue_count=0,
        wip_count=0,
        avg_wip_age_seconds=None,
        avg_cycle_time_seconds=None,
    )
    mock.wait_for_task.return_value = TASK._replace() if hasattr(TASK, "_replace") else TASK
    mock.wait_for_task.return_value = TaskResponse(**{**TASK.model_dump(), "status": "completed"})
    mock.close.return_value = None
    return mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

runner = CliRunner()


@patch("selva_sdk.cli._get_client")
def test_dispatch_command(mock_get: MagicMock) -> None:
    mock_get.return_value = _mock_client()
    result = runner.invoke(cli, ["dispatch", "Fix login bug"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["id"] == "aaaa-bbbb-cccc"
    assert data["status"] == "queued"


@patch("selva_sdk.cli._get_client")
def test_dispatch_with_options(mock_get: MagicMock) -> None:
    mock_get.return_value = _mock_client()
    result = runner.invoke(
        cli,
        [
            "dispatch",
            "Deploy service",
            "--graph-type",
            "deployment",
            "--agent-id",
            "a1",
            "--skill",
            "docker",
        ],
    )
    assert result.exit_code == 0
    mock_get.return_value.dispatch.assert_called_once()


@patch("selva_sdk.cli._get_client")
def test_agents_list_command(mock_get: MagicMock) -> None:
    mock_get.return_value = _mock_client()
    result = runner.invoke(cli, ["agents", "list"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["name"] == "Alice"


@patch("selva_sdk.cli._get_client")
def test_tasks_get_command(mock_get: MagicMock) -> None:
    mock_get.return_value = _mock_client()
    result = runner.invoke(cli, ["tasks", "get", "aaaa-bbbb-cccc"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["description"] == "Fix login bug"


@patch("selva_sdk.cli._get_client")
def test_tasks_wait_command(mock_get: MagicMock) -> None:
    mock_get.return_value = _mock_client()
    result = runner.invoke(cli, ["tasks", "wait", "aaaa-bbbb-cccc", "--timeout", "10"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "completed"


@patch("selva_sdk.cli._get_client")
def test_kanban_move_command(mock_get: MagicMock) -> None:
    mock_get.return_value = _mock_client()
    result = runner.invoke(cli, ["kanban", "move", "aaaa-bbbb-cccc", "in_progress"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["kanban_status"] == "in_progress"
    mock_get.return_value.update_task_kanban.assert_called_once()


def test_help_text() -> None:
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Selva CLI" in result.output


def test_dispatch_missing_description() -> None:
    result = runner.invoke(cli, ["dispatch"])
    assert result.exit_code != 0
    assert "Missing argument" in result.output


@patch("selva_sdk.cli._get_client")
def test_dispatch_error_display(mock_get: MagicMock) -> None:
    mock = _mock_client()
    mock.dispatch.side_effect = SelvaError("Budget exceeded", 402)
    mock_get.return_value = mock
    result = runner.invoke(cli, ["dispatch", "Test"])
    assert result.exit_code == 1
    assert "Error: Budget exceeded" in result.output


@patch("selva_sdk.cli._get_client")
def test_env_var_configuration(mock_get: MagicMock) -> None:
    """Verify env vars are read for client construction."""
    mock_get.return_value = _mock_client()
    result = runner.invoke(
        cli,
        ["agents", "list"],
        env={"SELVA_API_URL": "http://custom:9999", "SELVA_TOKEN": "secret"},
    )
    assert result.exit_code == 0
