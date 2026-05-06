"""Deployment tools for triggering and monitoring Enclii deploys."""

from __future__ import annotations

from typing import Any

from ..audience import Audience
from ..base import BaseTool, ToolResult


class DeployTool(BaseTool):
    name = "deploy_trigger"
    description = "Trigger a deployment via the Enclii platform"
    audience = Audience.PLATFORM

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Name of the service to deploy",
                },
                "environment": {
                    "type": "string",
                    "enum": ["staging", "production"],
                    "default": "staging",
                    "description": "Target environment",
                },
                "image_tag": {
                    "type": "string",
                    "default": "latest",
                    "description": "Docker image tag to deploy",
                },
            },
            "required": ["service"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        import os

        import httpx

        service = kwargs.get("service", "")
        environment = kwargs.get("environment", "staging")
        image_tag = kwargs.get("image_tag", "latest")

        enclii_url = os.environ.get("ENCLII_API_URL", "")
        enclii_token = os.environ.get("ENCLII_DEPLOY_TOKEN", "")

        if not enclii_url or not enclii_token:
            return ToolResult(
                success=False,
                error="ENCLII_API_URL and ENCLII_DEPLOY_TOKEN must be set",
            )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{enclii_url}/v1/deploy/trigger",
                    json={
                        "service": service,
                        "environment": environment,
                        "image_tag": image_tag,
                    },
                    headers={"Authorization": f"Bearer {enclii_token}"},
                )
                resp.raise_for_status()
                data = resp.json()
                return ToolResult(
                    output=f"Deploy triggered: {data.get('deploy_id', 'unknown')}",
                    data={
                        "deploy_id": data.get("deploy_id", ""),
                        "status": data.get("status", "pending"),
                    },
                )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


class DeployStatusTool(BaseTool):
    name = "deploy_status"
    description = "Check the status of an Enclii deployment"

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "deploy_id": {
                    "type": "string",
                    "description": "The deployment ID to check",
                },
            },
            "required": ["deploy_id"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        import os

        import httpx

        deploy_id = kwargs.get("deploy_id", "")

        enclii_url = os.environ.get("ENCLII_API_URL", "")
        enclii_token = os.environ.get("ENCLII_DEPLOY_TOKEN", "")

        if not enclii_url or not enclii_token:
            return ToolResult(
                success=False,
                error="ENCLII_API_URL and ENCLII_DEPLOY_TOKEN must be set",
            )

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{enclii_url}/v1/deploy/status/{deploy_id}",
                    headers={"Authorization": f"Bearer {enclii_token}"},
                )
                resp.raise_for_status()
                data = resp.json()
                return ToolResult(
                    output=f"Deploy {deploy_id}: {data.get('status', 'unknown')}",
                    data=data,
                )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
