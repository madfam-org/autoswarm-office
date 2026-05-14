"""Phygital Node tools — parametric design, DFM analysis, and manufacturing.

Implements Axiom III of the Swarm Governing Manifesto:
"We do not extrude until the digital twin has succeeded."

These tools bridge the digital-to-physical gap:
- Generate parametric 3D models via Yantra4D
- Run Design for Manufacturability analysis
- Generate fabrication quotes via Cotiza/Forgesight
- Create manufacturing work orders via Pravara-MES
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import quote

import httpx

from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

YANTRA4D_API_URL = os.environ.get("YANTRA4D_API_URL", "")
PRAVARA_MES_API_URL = os.environ.get("PRAVARA_MES_API_URL", "")
COTIZA_API_URL = os.environ.get("COTIZA_API_URL", "")
YANTRA4D_API_TOKEN = (
    os.environ.get("YANTRA4D_API_TOKEN")
    or os.environ.get("SELVA_YANTRA4D_SERVICE_TOKEN")
    or os.environ.get("SELVA_SERVICE_TOKEN")
    or ""
)
COTIZA_API_TOKEN = (
    os.environ.get("COTIZA_API_TOKEN")
    or os.environ.get("SELVA_COTIZA_SERVICE_TOKEN")
    or os.environ.get("SELVA_SERVICE_TOKEN")
    or ""
)


def _service_auth_headers(token: str) -> dict[str, str]:
    token = str(token or "").strip()
    if not token:
        return {}
    return {
        "Authorization": f"Bearer {token}",
        "X-Service-Actor": "selva-agent",
    }


class GenerateParametricModelTool(BaseTool):
    """Generate a parametric 3D model via Yantra4D.

    Takes geometric parameters and material specs, returns a model ID
    that can be passed to DFM analysis and quote generation.
    """

    name = "generate_parametric_model"
    description = (
        "Generate a parametric 3D model from specifications via Yantra4D. "
        "Returns a model ID for DFM analysis and manufacturing. "
        "Use when you need to create a 3D design from parameters."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Model name/identifier"},
                "geometry_type": {
                    "type": "string",
                    "description": "Base geometry (box, cylinder, sphere, custom)",
                    "default": "custom",
                },
                "dimensions": {
                    "type": "object",
                    "description": "Dimension parameters (e.g., {width: 100, height: 50, depth: 30} in mm)",  # noqa: E501
                },
                "material": {
                    "type": "string",
                    "description": "Material (PLA, ABS, PETG, Nylon-CF, PEEK, TPU)",
                    "default": "PLA",
                },
                "infill_percent": {
                    "type": "integer",
                    "description": "Infill density percentage (0-100)",
                    "default": 20,
                },
            },
            "required": ["name", "dimensions"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not YANTRA4D_API_URL:
            return ToolResult(success=False, error="YANTRA4D_API_URL not configured")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{YANTRA4D_API_URL}/api/v1/models/generate",
                    json={
                        "name": kwargs.get("name", ""),
                        "geometry_type": kwargs.get("geometry_type", "custom"),
                        "dimensions": kwargs.get("dimensions", {}),
                        "material": kwargs.get("material", "PLA"),
                        "infill_percent": kwargs.get("infill_percent", 20),
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            model_id = data.get("model_id", data.get("id", "unknown"))
            return ToolResult(
                success=True,
                output=f"Parametric model generated: {model_id} ({kwargs.get('name', '')})",
                data=data,
            )
        except httpx.HTTPError as exc:
            return ToolResult(success=False, error=f"Model generation failed: {exc}")


class RunDFMAnalysisTool(BaseTool):
    """Run Design for Manufacturability analysis on a 3D model.

    Checks if a model can be successfully fabricated with the specified
    material and process. Implements Axiom III: digital twin must succeed
    before physical extrusion.
    """

    name = "run_dfm_analysis"
    description = (
        "Analyze a 3D model for manufacturability (DFM). "
        "Checks wall thickness, overhangs, support requirements, and material compatibility. "
        "The model MUST pass DFM before fabrication can proceed (Axiom III)."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "model_id": {"type": "string", "description": "ID of the model to analyze"},
                "process": {
                    "type": "string",
                    "description": "Manufacturing process (fdm, sla, sls, cnc)",
                    "default": "fdm",
                },
                "material": {
                    "type": "string",
                    "description": "Target material",
                    "default": "PLA",
                },
            },
            "required": ["model_id"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not YANTRA4D_API_URL:
            return ToolResult(success=False, error="YANTRA4D_API_URL not configured")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{YANTRA4D_API_URL}/api/v1/models/{kwargs['model_id']}/dfm",
                    json={
                        "process": kwargs.get("process", "fdm"),
                        "material": kwargs.get("material", "PLA"),
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            passed = data.get("passed", False)
            issues = data.get("issues", [])
            status = "PASSED" if passed else f"FAILED ({len(issues)} issues)"

            return ToolResult(
                success=True,
                output=f"DFM Analysis: {status}. {'; '.join(issues[:3]) if issues else 'No issues found.'}",  # noqa: E501
                data=data,
            )
        except httpx.HTTPError as exc:
            return ToolResult(success=False, error=f"DFM analysis failed: {exc}")


class GenerateQuoteTool(BaseTool):
    """Generate a fabrication quote using the Yantra/Cotiza quote contract."""

    name = "generate_quote"
    description = (
        "Generate a fabrication price quote for a 3D model. "
        "Uses Cotiza/Forgesight pricing intelligence for accurate estimates."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project_slug": {
                    "type": "string",
                    "description": (
                        "Yantra4D project slug. When provided, Selva requests the "
                        "quote through Yantra4D's project endpoint."
                    ),
                },
                "geometry": {
                    "type": "object",
                    "description": (
                        "Structured geometry data required by Cotiza when no "
                        "project_slug is available."
                    ),
                },
                "project": {
                    "type": "object",
                    "description": (
                        "Structured project metadata required by Cotiza when no "
                        "project_slug is available."
                    ),
                },
                "model_id": {
                    "type": "string",
                    "description": "Optional Yantra4D model ID for traceability",
                },
                "material": {"type": "string", "default": "PLA"},
                "quantity": {"type": "integer", "default": 1, "description": "Number of units"},
                "process": {"type": "string", "default": "fdm"},
                "priority": {
                    "type": "string",
                    "enum": ["standard", "express", "rush"],
                    "default": "standard",
                },
                "finish": {"type": "string", "default": "standard"},
                "currency": {"type": "string", "default": "MXN"},
                "notes": {"type": "string", "default": ""},
                "require_market_verified": {
                    "type": "boolean",
                    "default": True,
                    "description": "Require Cotiza/Forgesight market-verified pricing.",
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        project_slug = str(kwargs.get("project_slug") or "").strip()
        require_market_verified = bool(kwargs.get("require_market_verified", True))

        quote_context = {
            "material": kwargs.get("material", "PLA"),
            "quantity": kwargs.get("quantity", 1),
            "process": kwargs.get("process", "fdm"),
            "priority": kwargs.get("priority", "standard"),
            "finish": kwargs.get("finish", "standard"),
            "currency": kwargs.get("currency", "MXN"),
            "notes": kwargs.get("notes", ""),
            "require_market_verified": require_market_verified,
        }
        if kwargs.get("model_id"):
            quote_context["model_id"] = kwargs["model_id"]

        if project_slug:
            if not YANTRA4D_API_URL:
                return ToolResult(success=False, error="YANTRA4D_API_URL not configured")
            api_url = YANTRA4D_API_URL.rstrip("/")
            endpoint = f"{api_url}/api/projects/{quote(project_slug, safe='')}/cotiza-quote-request"
            payload = quote_context
        else:
            if not COTIZA_API_URL:
                return ToolResult(success=False, error="COTIZA_API_URL not configured")
            geometry = kwargs.get("geometry")
            project = kwargs.get("project")
            if not isinstance(geometry, dict) or not geometry:
                return ToolResult(
                    success=False,
                    error="geometry is required for Cotiza quote requests without project_slug",
                )
            if not isinstance(project, dict) or not project:
                return ToolResult(
                    success=False,
                    error="project is required for Cotiza quote requests without project_slug",
                )
            api_url = COTIZA_API_URL.rstrip("/")
            endpoint = f"{api_url}/api/v1/quotes/from-yantra4d"
            process_map = {
                "fdm": "3d_fff",
                "fff": "3d_fff",
                "3d_fff": "3d_fff",
                "sla": "3d_sla",
                "3d_sla": "3d_sla",
                "cnc": "cnc_3axis",
                "cnc_3axis": "cnc_3axis",
                "laser": "laser_2d",
                "laser_2d": "laser_2d",
            }
            raw_process = str(kwargs.get("process", "fdm")).lower()
            cotiza_process = process_map.get(raw_process, "3d_fff")
            project_name = str(project.get("name") or project.get("slug") or "Yantra4D project")
            payload = {
                "source": "yantra4d",
                "project": project,
                "geometry": geometry,
                "item": {
                    "name": project_name,
                    "process": cotiza_process,
                    "material": quote_context["material"],
                    "quantity": quote_context["quantity"],
                    "finish": quote_context["finish"],
                    "options": {
                        "priority": quote_context["priority"],
                        "require_market_verified": require_market_verified,
                    },
                },
                "currency": quote_context["currency"],
                "notes": quote_context["notes"],
                "require_market_verified": require_market_verified,
            }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                request_kwargs: dict[str, Any] = {"json": payload}
                headers = _service_auth_headers(
                    YANTRA4D_API_TOKEN if project_slug else COTIZA_API_TOKEN
                )
                if headers:
                    request_kwargs["headers"] = headers
                resp = await client.post(
                    endpoint,
                    **request_kwargs,
                )
                resp.raise_for_status()
                data = resp.json()

            price = data.get("totalPrice", data.get("total_price", data.get("total")))
            currency = data.get("currency", "MXN")
            quote_id = data.get("quoteId", data.get("quote_id", data.get("id", "pending")))
            market_verified = bool(
                data.get("market_verified")
                or (data.get("market_context") or {}).get("market_verified")
                or (data.get("cotiza_quote") or {}).get("market_verified")
            )
            if require_market_verified and not market_verified:
                return ToolResult(
                    success=False,
                    error="Quote was created/submitted but is not market verified",
                    data=data,
                )
            if price is None:
                output = f"Quote request submitted: {quote_id}"
            else:
                output = (
                    f"Quote generated: {currency} ${float(price):.2f} "
                    f"for {kwargs.get('quantity', 1)} unit(s)"
                )
            return ToolResult(
                success=True,
                output=output,
                data=data,
            )
        except httpx.HTTPError as exc:
            return ToolResult(success=False, error=f"Quote generation failed: {exc}")


class CreateWorkOrderTool(BaseTool):
    """Create a manufacturing work order in Pravara-MES.

    This is the physical execution step. Per Axiom III, this should ONLY
    be called after DFM analysis passes. The phygital graph enforces this
    with a mandatory HITL review gate before work order creation.
    """

    name = "create_work_order"
    description = (
        "Create a manufacturing work order in the MES. "
        "IMPORTANT: Only use after DFM analysis has passed. "
        "This triggers actual physical fabrication."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "model_id": {"type": "string", "description": "Model ID (must have passed DFM)"},
                "quantity": {"type": "integer", "default": 1},
                "material": {"type": "string", "default": "PLA"},
                "priority": {
                    "type": "string",
                    "enum": ["low", "normal", "high", "urgent"],
                    "default": "normal",
                },
                "notes": {"type": "string", "default": ""},
            },
            "required": ["model_id"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not PRAVARA_MES_API_URL:
            return ToolResult(success=False, error="PRAVARA_MES_API_URL not configured")

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{PRAVARA_MES_API_URL}/api/v1/work-orders",
                    json={
                        "model_id": kwargs.get("model_id", ""),
                        "quantity": kwargs.get("quantity", 1),
                        "material": kwargs.get("material", "PLA"),
                        "priority": kwargs.get("priority", "normal"),
                        "notes": kwargs.get("notes", ""),
                        "source": "selva-agent",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            order_id = data.get("work_order_id", data.get("id", "unknown"))
            return ToolResult(
                success=True,
                output=f"Work order created: {order_id} (qty: {kwargs.get('quantity', 1)}, material: {kwargs.get('material', 'PLA')})",  # noqa: E501
                data=data,
            )
        except httpx.HTTPError as exc:
            return ToolResult(success=False, error=f"Work order creation failed: {exc}")
