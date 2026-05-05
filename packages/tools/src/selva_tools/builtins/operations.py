"""Operations tools -- pedimento lookup, carrier tracking, inventory check."""

from __future__ import annotations

import logging
import os
from typing import Any

from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_VALID_CARRIERS = ("estafeta", "fedex", "dhl", "paquetexpress")


class PedimentoLookupTool(BaseTool):
    name = "pedimento_lookup"
    description = "Look up customs pedimento document via Karafiel SAT module"

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "numero": {
                    "type": "string",
                    "description": ("Pedimento number (e.g. '26 48 3180 6001234')"),
                },
            },
            "required": ["numero"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        numero: str = kwargs.get("numero", "").strip()
        if not numero:
            return ToolResult(success=False, error="numero is required")

        try:
            from madfam_inference.adapters.karafiel import KarafielAdapter

            adapter = KarafielAdapter()
            result = await adapter.get_pedimento(numero)
            return ToolResult(
                success=True,
                output=f"Pedimento {numero}: {result.get('status', 'found')}",
                data=result,
            )
        except ImportError:
            return ToolResult(
                success=False,
                error="Karafiel adapter not available. Install madfam-inference.",
            )
        except Exception as exc:
            logger.warning("Pedimento lookup failed for %s: %s", numero, exc)
            return ToolResult(success=False, error=str(exc))


class CarrierTrackingTool(BaseTool):
    name = "carrier_tracking"
    description = (
        "Track shipment status with Mexican carriers (Estafeta, FedEx MX, DHL, PaqueteExpress)"
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "carrier": {
                    "type": "string",
                    "enum": list(_VALID_CARRIERS),
                    "description": "Carrier name",
                },
                "tracking_number": {
                    "type": "string",
                    "description": "Shipment tracking number",
                },
            },
            "required": ["carrier", "tracking_number"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        carrier: str = kwargs.get("carrier", "").lower().strip()
        tracking_number: str = kwargs.get("tracking_number", "").strip()

        if not carrier or not tracking_number:
            return ToolResult(success=False, error="carrier and tracking_number are required")

        if carrier not in _VALID_CARRIERS:
            return ToolResult(
                success=False,
                error=f"Unsupported carrier '{carrier}'. Valid: {', '.join(_VALID_CARRIERS)}",
            )

        # Check if the carrier API key is configured
        env_key_map = {
            "estafeta": "ESTAFETA_API_KEY",
            "fedex": "FEDEX_MX_API_KEY",
            "dhl": "DHL_API_KEY",
            "paquetexpress": "PAQUETEXPRESS_API_KEY",
        }
        api_key_var = env_key_map.get(carrier, "")
        api_key = os.environ.get(api_key_var, "")

        if not api_key:
            return ToolResult(
                success=True,
                output=(
                    f"Carrier tracking for {carrier} / {tracking_number}: "
                    "tracking_service_not_configured"
                ),
                data={
                    "carrier": carrier,
                    "tracking_number": tracking_number,
                    "status": "tracking_service_not_configured",
                    "message": (
                        f"Set {api_key_var} environment variable to enable {carrier} tracking."
                    ),
                },
            )

        # Future enhancement: actual carrier API integration
        return ToolResult(
            success=True,
            output=(
                f"Carrier tracking for {carrier} / {tracking_number}: "
                "tracking_service_not_configured"
            ),
            data={
                "carrier": carrier,
                "tracking_number": tracking_number,
                "status": "tracking_service_not_configured",
                "message": "Full carrier API integration is a future enhancement.",
            },
        )


class InventoryCheckTool(BaseTool):
    name = "inventory_check"
    description = "Check inventory levels (via Dhanam or PravaraMES if configured)"

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "sku": {
                    "type": "string",
                    "description": "Product SKU to check",
                },
                "warehouse": {
                    "type": "string",
                    "description": "Warehouse code (optional, defaults to all)",
                },
            },
            "required": ["sku"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        sku: str = kwargs.get("sku", "").strip()
        warehouse: str = kwargs.get("warehouse", "").strip()

        if not sku:
            return ToolResult(success=False, error="sku is required")

        # NOTE: a previous version tried ``DhanamAdapter().get_inventory(...)``
        # but Dhanam is the billing/economic-data adapter and never had an
        # inventory method. The AttributeError was silently swallowed, making
        # the tool look like it was "trying Dhanam first" when in reality it
        # always fell through to PravaraMES. Removed.
        # Try PravaraMES
        pravara_url = os.environ.get("PRAVARA_MES_API_URL", "")
        if pravara_url:
            try:
                import httpx

                async with httpx.AsyncClient(timeout=10.0) as client:
                    params: dict[str, str] = {"sku": sku}
                    if warehouse:
                        params["warehouse"] = warehouse
                    resp = await client.get(
                        f"{pravara_url.rstrip('/')}/api/v1/inventory/check",
                        params=params,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    return ToolResult(
                        success=True,
                        output=f"Inventory for SKU {sku}: {data.get('quantity', 'N/A')} units",
                        data=data,
                    )
            except Exception as exc:
                logger.warning("PravaraMES inventory check failed: %s", exc)
                return ToolResult(success=False, error=str(exc))

        return ToolResult(
            success=True,
            output=f"Inventory for SKU {sku}: inventory service not configured",
            data={
                "sku": sku,
                "warehouse": warehouse or "all",
                "status": "inventory_service_not_configured",
                "message": (
                    "Set PRAVARA_MES_API_URL or install madfam-inference with "
                    "Dhanam adapter to enable inventory checks."
                ),
            },
        )
