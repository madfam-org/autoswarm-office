"""Worker-to-API authentication helpers."""

from __future__ import annotations


def get_worker_auth_headers(org_id: str | None = None) -> dict[str, str]:
    """Return Authorization headers for worker-to-API calls.

    Reads the token from ``WORKER_API_TOKEN`` env var (via settings).

    Args:
        org_id: Target tenant org_id. Required for tenant-scoped operations
            (task events, voice-mode lookup, billing, agent stats, etc.).
            Sent as the ``X-Selva-Tenant-Org`` header so nexus-api ``auth.py``
            can populate ``user["org_id"]`` correctly for the worker token
            path. Omit only for genuinely platform-scoped service calls
            (audit writes, queue stats) where the receiving endpoint
            verifies the ``service`` role.
    """
    from .config import get_settings

    headers = {"Authorization": f"Bearer {get_settings().worker_api_token}"}
    if org_id:
        headers["X-Selva-Tenant-Org"] = org_id
    return headers
