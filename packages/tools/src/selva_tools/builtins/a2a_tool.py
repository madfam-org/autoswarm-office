"""A2A protocol tool -- discover and call external A2A-compatible agents."""

from __future__ import annotations

from typing import Any

from ..base import BaseTool, ToolResult


class CallExternalAgentTool(BaseTool):
    """Discover and invoke an external agent via the A2A protocol.

    This tool allows Selva agents to delegate tasks to other
    A2A-compatible agents running on different platforms (CrewAI,
    LangGraph, MS Agent Framework, etc.).
    """

    name = "call_external_agent"
    description = (
        "Discover and call an external A2A-compatible agent. "
        "Sends a task to a remote agent and returns the task ID and status."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_url": {
                    "type": "string",
                    "description": "Base URL of the remote A2A agent (e.g. https://agent.example.com/a2a)",
                },
                "task_description": {
                    "type": "string",
                    "description": "Description of the task to send to the remote agent",
                },
                "graph_type": {
                    "type": "string",
                    "default": "coding",
                    "description": "Graph type hint for the remote agent",
                },
                "token": {
                    "type": "string",
                    "description": "Optional Bearer token for authenticating with the remote agent",
                },
            },
            "required": ["agent_url", "task_description"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        agent_url: str = kwargs.get("agent_url", "")
        task_description: str = kwargs.get("task_description", "")
        graph_type: str = kwargs.get("graph_type", "coding")
        token: str | None = kwargs.get("token")

        if not agent_url or not task_description:
            return ToolResult(
                success=False,
                error="agent_url and task_description are required",
            )

        try:
            from selva_a2a import A2AClient, TaskRequest

            client = A2AClient(timeout=60.0)

            # Step 1: Discover the remote agent
            card = await client.discover(agent_url)

            # Step 2: Send the task
            task_req = TaskRequest(
                description=task_description,
                graph_type=graph_type,
            )
            resp = await client.send_task(agent_url, task_req, token=token)

            return ToolResult(
                output=(f"Task sent to {card.name}: task_id={resp.task_id}, status={resp.status}"),
                data={
                    "task_id": resp.task_id,
                    "status": resp.status,
                    "remote_agent": card.name,
                    "remote_capabilities": card.capabilities,
                },
            )
        except ImportError:
            return ToolResult(
                success=False,
                error="selva-a2a package is not installed",
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
