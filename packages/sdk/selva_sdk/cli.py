"""CLI for dispatching tasks and querying Selva."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

from .client import SelvaSync
from .exceptions import SelvaError


def _get_client() -> SelvaSync:
    """Build a sync client from environment variables."""
    base_url = os.environ.get("SELVA_API_URL", "http://localhost:4300")
    token = os.environ.get("SELVA_TOKEN", "dev-token")
    return SelvaSync(base_url=base_url, token=token)


@click.group()
def cli() -> None:
    """Selva CLI — interact with the Selva Office API."""


# -- dispatch ----------------------------------------------------------------


@cli.command()
@click.argument("description")
@click.option("--title", default=None, help="Short kanban card title.")
@click.option("--graph-type", default="coding", help="Graph type for the task.")
@click.option("--agent-id", multiple=True, help="Agent IDs to assign (repeatable).")
@click.option("--skill", multiple=True, help="Required skills (repeatable).")
@click.option("--workflow-id", default=None, help="Workflow UUID for custom graphs.")
@click.option("--priority", default="medium", help="Kanban priority.")
@click.option("--label", multiple=True, help="Kanban labels (repeatable).")
@click.option("--due-date", default=None, help="ISO-8601 due date.")
def dispatch(
    description: str,
    title: str | None,
    graph_type: str,
    agent_id: tuple[str, ...],
    skill: tuple[str, ...],
    workflow_id: str | None,
    priority: str,
    label: tuple[str, ...],
    due_date: str | None,
) -> None:
    """Dispatch a new swarm task."""
    client = _get_client()
    try:
        task = client.dispatch(
            description=description,
            title=title,
            graph_type=graph_type,
            assigned_agent_ids=list(agent_id),
            required_skills=list(skill),
            workflow_id=workflow_id,
            priority=priority,
            labels=list(label),
            due_date=due_date,
        )
        click.echo(json.dumps(task.model_dump(), indent=2))
    except SelvaError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        client.close()


# -- agents ------------------------------------------------------------------


@cli.group()
def agents() -> None:
    """Agent management commands."""


@agents.command("list")
def agents_list() -> None:
    """List all agents."""
    client = _get_client()
    try:
        agent_list = client.list_agents()
        click.echo(json.dumps([a.model_dump() for a in agent_list], indent=2))
    except SelvaError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        client.close()


# -- tasks -------------------------------------------------------------------


@cli.group()
def tasks() -> None:
    """Task management commands."""


@tasks.command("get")
@click.argument("task_id")
def tasks_get(task_id: str) -> None:
    """Get a task by ID."""
    client = _get_client()
    try:
        task = client.get_task(task_id)
        click.echo(json.dumps(task.model_dump(), indent=2))
    except SelvaError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        client.close()


@tasks.command("wait")
@click.argument("task_id")
@click.option("--timeout", default=300.0, type=float, help="Timeout in seconds.")
@click.option("--poll-interval", default=2.0, type=float, help="Poll interval in seconds.")
def tasks_wait(task_id: str, timeout: float, poll_interval: float) -> None:
    """Wait for a task to reach a terminal status."""
    client = _get_client()
    try:
        task = client.wait_for_task(task_id, poll_interval=poll_interval, timeout=timeout)
        click.echo(json.dumps(task.model_dump(), indent=2))
    except SelvaError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        client.close()


# -- kanban ------------------------------------------------------------------


@cli.group()
def kanban() -> None:
    """Kanban task-board commands."""


@kanban.command("list")
@click.option("--status", "status_filter", default=None, help="Filter by kanban status.")
def kanban_list(status_filter: str | None) -> None:
    """List kanban tasks grouped by status."""
    client = _get_client()
    try:
        board = client.get_kanban_board()
        if status_filter:
            tasks_out = [item.model_dump() for item in board.columns.get(status_filter, [])]
            click.echo(json.dumps(tasks_out, indent=2))
        else:
            click.echo(json.dumps(board.model_dump(), indent=2))
    except SelvaError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        client.close()


@kanban.command("create")
@click.argument("description")
@click.option("--title", default=None, help="Short kanban card title.")
@click.option("--priority", default="medium", help="Kanban priority.")
@click.option("--label", multiple=True, help="Kanban labels (repeatable).")
@click.option("--due-date", default=None, help="ISO-8601 due date.")
def kanban_create(
    description: str,
    title: str | None,
    priority: str,
    label: tuple[str, ...],
    due_date: str | None,
) -> None:
    """Create a kanban-backed swarm task."""
    client = _get_client()
    try:
        task = client.dispatch(
            description=description,
            title=title,
            graph_type="sequential",
            priority=priority,
            labels=list(label),
            due_date=due_date,
        )
        click.echo(json.dumps(task.model_dump(), indent=2))
    except SelvaError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        client.close()


@kanban.command("move")
@click.argument("task_id")
@click.argument("status")
def kanban_move(task_id: str, status: str) -> None:
    """Move a task to a kanban status."""
    client = _get_client()
    try:
        task = client.update_task_kanban(task_id, kanban_status=status)
        click.echo(json.dumps(task.model_dump(), indent=2))
    except SelvaError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        client.close()


@kanban.command("comment")
@click.argument("task_id")
@click.argument("body")
def kanban_comment(task_id: str, body: str) -> None:
    """Add a durable task comment."""
    client = _get_client()
    try:
        comment = client.add_task_comment(task_id, body)
        click.echo(json.dumps(comment.model_dump(), indent=2))
    except SelvaError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        client.close()


@kanban.command("history")
@click.argument("task_id")
def kanban_history(task_id: str) -> None:
    """Show append-only task history."""
    client = _get_client()
    try:
        history = client.get_task_history(task_id)
        click.echo(json.dumps([item.model_dump() for item in history], indent=2))
    except SelvaError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        client.close()


@kanban.command("claim")
@click.option("--agent-id", default=None, help="Agent ID claiming work.")
@click.option("--graph-type", default=None, help="Optional graph-type filter.")
@click.option("--label", multiple=True, help="Required labels (repeatable).")
def kanban_claim(agent_id: str | None, graph_type: str | None, label: tuple[str, ...]) -> None:
    """Claim the next available task."""
    client = _get_client()
    try:
        claimed = client.claim_task(agent_id=agent_id, graph_type=graph_type, labels=list(label))
        click.echo(json.dumps(claimed.model_dump(), indent=2))
    except SelvaError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        client.close()


@kanban.command("notify-overdue")
def kanban_notify_overdue() -> None:
    """Emit overdue lifecycle notifications for active tasks."""
    client = _get_client()
    try:
        result = client.notify_overdue_tasks()
        click.echo(json.dumps(result.model_dump(), indent=2))
    except SelvaError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        client.close()


@kanban.command("export")
@click.option("--format", "export_format", default="json", type=click.Choice(["json", "csv"]))
@click.option("--status", "status_filter", default=None, help="Filter by kanban status.")
def kanban_export(export_format: str, status_filter: str | None) -> None:
    """Export kanban tasks as JSON or CSV."""
    client = _get_client()
    try:
        exported = client.export_kanban_tasks(format=export_format, kanban_status=status_filter)
        if isinstance(exported, str):
            click.echo(exported, nl=False)
        else:
            click.echo(json.dumps(exported, indent=2))
    except SelvaError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        client.close()


@kanban.command("import")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--format", "import_format", default="json", type=click.Choice(["json", "csv"]))
def kanban_import(path: Path, import_format: str) -> None:
    """Import kanban tasks from a JSON or CSV file."""
    client = _get_client()
    try:
        raw = path.read_text(encoding="utf-8")
        payload = raw if import_format == "csv" else json.loads(raw)
        imported = client.import_kanban_tasks(payload, format=import_format)
        click.echo(json.dumps(imported.model_dump(), indent=2))
    except SelvaError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        client.close()


@kanban.command("metrics")
def kanban_metrics() -> None:
    """Show kanban-specific metrics."""
    client = _get_client()
    try:
        metrics = client.get_kanban_metrics()
        click.echo(json.dumps(metrics.model_dump(), indent=2))
    except SelvaError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    finally:
        client.close()
