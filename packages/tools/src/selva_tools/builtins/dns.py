"""Porkbun DNS management tools for the Selva Swarm.

Provides domain listing, NS management, and DNS record CRUD via the
Porkbun API v3. Used by infrastructure agents for domain provisioning,
NS delegation to Cloudflare, and DNS health checks.

API Docs: https://porkbun.com/api/json/v3/documentation
Auth: Requires PORKBUN_API_KEY and PORKBUN_SECRET_KEY env vars.

NOTE: Domains must have "API Access" enabled in the Porkbun dashboard
(Domain Management → Details → API Access toggle) before API calls work.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ..audience import Audience
from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

PORKBUN_API_BASE = "https://api.porkbun.com/api/json/v3"
PORKBUN_API_KEY = os.environ.get("PORKBUN_API_KEY", "")
PORKBUN_SECRET_KEY = os.environ.get("PORKBUN_SECRET_KEY", "")


def _auth_body() -> dict[str, str]:
    """Return the auth payload required by all Porkbun API calls."""
    return {
        "apikey": PORKBUN_API_KEY,
        "secretapikey": PORKBUN_SECRET_KEY,
    }


def _check_credentials() -> str | None:
    """Return an error message if credentials are missing, else None."""
    if not PORKBUN_API_KEY or not PORKBUN_SECRET_KEY:
        return (
            "PORKBUN_API_KEY and PORKBUN_SECRET_KEY must be set. "
            "Get them from https://porkbun.com/account/api"
        )
    return None


async def _post(path: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """POST to the Porkbun API and return the JSON response."""
    url = f"{PORKBUN_API_BASE}/{path}"
    body = _auth_body()
    if extra:
        body.update(extra)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=body)
        return resp.json()


# ---------------------------------------------------------------------------
# Tool: List all domains
# ---------------------------------------------------------------------------


class ListDomainsTool(BaseTool):
    """List all domains in the Porkbun account with status and expiry."""

    name = "porkbun_list_domains"
    description = (
        "List all domains registered in the MADFAM Porkbun account. "
        "Returns domain name, status, expiry date, and auto-renew setting."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        if err := _check_credentials():
            return ToolResult(success=False, error=err)
        try:
            data = await _post("domain/listAll")
            if data.get("status") != "SUCCESS":
                return ToolResult(success=False, error=data.get("message", "Unknown error"))
            domains = data.get("domains", [])
            lines = []
            for d in domains:
                dom = d["domain"]
                status = d["status"]
                exp = d.get("expireDate", "?")[:10]
                ar = "auto" if str(d.get("autoRenew")) == "1" else "manual"
                lines.append(f"  {dom:30s} {status:8s} exp={exp} renew={ar}")
            output = f"Total: {len(domains)} domains\n" + "\n".join(lines)
            return ToolResult(
                success=True,
                output=output,
                data={"domains": domains, "count": len(domains)},
            )
        except Exception as e:
            logger.error("porkbun_list_domains failed: %s", e)
            return ToolResult(success=False, error=str(e))


# ---------------------------------------------------------------------------
# Tool: Get nameservers for a domain
# ---------------------------------------------------------------------------


class GetNameserversTool(BaseTool):
    """Get the current nameservers for a domain."""

    name = "porkbun_get_nameservers"
    description = (
        "Get the current nameserver records for a domain. "
        "Useful to check if a domain is delegated to Cloudflare or still on Porkbun defaults."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "The domain to query (e.g. 'routecraft.app')",
                },
            },
            "required": ["domain"],
        }

    async def execute(self, *, domain: str, **kwargs: Any) -> ToolResult:  # type: ignore[override]
        if err := _check_credentials():
            return ToolResult(success=False, error=err)
        try:
            data = await _post(f"domain/getNs/{domain}")
            if data.get("status") != "SUCCESS":
                return ToolResult(success=False, error=data.get("message", "Unknown error"))
            ns = data.get("ns", [])
            is_cloudflare = any("cloudflare" in n for n in ns)
            is_porkbun = any("porkbun" in n for n in ns)
            output = (
                f"Domain: {domain}\n"
                f"Nameservers: {', '.join(ns)}\n"
                f"Delegated to: {'Cloudflare' if is_cloudflare else 'Porkbun' if is_porkbun else 'Other'}"  # noqa: E501
            )
            return ToolResult(
                success=True,
                output=output,
                data={"domain": domain, "ns": ns, "is_cloudflare": is_cloudflare},
            )
        except Exception as e:
            logger.error("porkbun_get_nameservers failed for %s: %s", domain, e)
            return ToolResult(success=False, error=str(e))


# ---------------------------------------------------------------------------
# Tool: Update nameservers (delegate to Cloudflare)
# ---------------------------------------------------------------------------


class UpdateNameserversTool(BaseTool):
    """Update nameservers for a domain (e.g., delegate to Cloudflare)."""

    name = "porkbun_update_nameservers"
    description = (
        "Update the nameservers for a domain. Typically used to delegate "
        "a domain from Porkbun defaults to Cloudflare for tunnel routing. "
        "Common Cloudflare NS: gene.ns.cloudflare.com, javier.ns.cloudflare.com"
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "The domain to update (e.g. 'factl.as')",
                },
                "nameservers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of nameserver hostnames",
                },
            },
            "required": ["domain", "nameservers"],
        }

    async def execute(self, *, domain: str, nameservers: list[str], **kwargs: Any) -> ToolResult:  # type: ignore[override]
        if err := _check_credentials():
            return ToolResult(success=False, error=err)
        if len(nameservers) < 2:
            return ToolResult(success=False, error="At least 2 nameservers required")
        try:
            data = await _post(f"domain/updateNs/{domain}", {"ns": nameservers})
            if data.get("status") != "SUCCESS":
                return ToolResult(success=False, error=data.get("message", "Unknown error"))
            output = f"Nameservers updated for {domain}: {', '.join(nameservers)}"
            return ToolResult(
                success=True,
                output=output,
                data={"domain": domain, "ns": nameservers},
            )
        except Exception as e:
            logger.error("porkbun_update_nameservers failed for %s: %s", domain, e)
            return ToolResult(success=False, error=str(e))


# ---------------------------------------------------------------------------
# Tool: List DNS records
# ---------------------------------------------------------------------------


class ListDnsRecordsTool(BaseTool):
    """List all DNS records for a domain."""

    name = "porkbun_list_dns_records"
    description = (
        "List all DNS records (A, AAAA, CNAME, MX, TXT, etc.) for a domain. "
        "Useful for auditing current DNS configuration."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "The domain to query (e.g. 'madfam.io')",
                },
            },
            "required": ["domain"],
        }

    async def execute(self, *, domain: str, **kwargs: Any) -> ToolResult:  # type: ignore[override]
        if err := _check_credentials():
            return ToolResult(success=False, error=err)
        try:
            data = await _post(f"dns/retrieve/{domain}")
            if data.get("status") != "SUCCESS":
                return ToolResult(success=False, error=data.get("message", "Unknown error"))
            records = data.get("records", [])
            lines = []
            for r in records:
                name = r.get("name", "@")
                rtype = r.get("type", "?")
                content = r.get("content", "")
                ttl = r.get("ttl", "")
                lines.append(f"  {rtype:6s} {name:40s} → {content} (TTL={ttl})")
            output = f"DNS records for {domain}: {len(records)} records\n" + "\n".join(lines)
            return ToolResult(
                success=True,
                output=output,
                data={"domain": domain, "records": records},
            )
        except Exception as e:
            logger.error("porkbun_list_dns_records failed for %s: %s", domain, e)
            return ToolResult(success=False, error=str(e))


# ---------------------------------------------------------------------------
# Tool: Create DNS record
# ---------------------------------------------------------------------------


class CreateDnsRecordTool(BaseTool):
    """Create a DNS record for a domain."""

    name = "porkbun_create_dns_record"
    description = (
        "Create a DNS record (A, AAAA, CNAME, MX, TXT, etc.) for a domain. "
        "Used for setting up subdomains, email routing, or verification records."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "The domain (e.g. 'madfam.io')",
                },
                "record_type": {
                    "type": "string",
                    "enum": ["A", "AAAA", "CNAME", "MX", "TXT", "NS", "SRV", "CAA"],
                    "description": "DNS record type",
                },
                "name": {
                    "type": "string",
                    "description": "Subdomain or '@' for root (e.g. 'www', 'api', '@')",
                },
                "content": {
                    "type": "string",
                    "description": "Record value (IP, hostname, or text)",
                },
                "ttl": {
                    "type": "integer",
                    "description": "TTL in seconds (default 600)",
                },
                "prio": {
                    "type": "integer",
                    "description": "Priority (for MX/SRV records)",
                },
            },
            "required": ["domain", "record_type", "content"],
        }

    async def execute(  # type: ignore[override]
        self,
        *,
        domain: str,
        record_type: str,
        content: str,
        name: str = "",
        ttl: int = 600,
        prio: int | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        if err := _check_credentials():
            return ToolResult(success=False, error=err)
        try:
            extra: dict[str, Any] = {
                "type": record_type,
                "content": content,
                "ttl": str(ttl),
            }
            if name:
                extra["name"] = name
            if prio is not None:
                extra["prio"] = str(prio)

            data = await _post(f"dns/create/{domain}", extra)
            if data.get("status") != "SUCCESS":
                return ToolResult(success=False, error=data.get("message", "Unknown error"))
            record_id = data.get("id", "?")
            output = f"Created {record_type} record for {name or '@'}.{domain} → {content} (id={record_id})"  # noqa: E501
            return ToolResult(
                success=True,
                output=output,
                data={"domain": domain, "record_id": record_id},
            )
        except Exception as e:
            logger.error("porkbun_create_dns_record failed for %s: %s", domain, e)
            return ToolResult(success=False, error=str(e))


# ---------------------------------------------------------------------------
# Tool: Delete DNS record
# ---------------------------------------------------------------------------


class DeleteDnsRecordTool(BaseTool):
    """Delete a DNS record by ID."""

    name = "porkbun_delete_dns_record"
    description = "Delete a specific DNS record by its Porkbun record ID."

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "The domain (e.g. 'madfam.io')",
                },
                "record_id": {
                    "type": "string",
                    "description": "The Porkbun record ID to delete",
                },
            },
            "required": ["domain", "record_id"],
        }

    async def execute(self, *, domain: str, record_id: str, **kwargs: Any) -> ToolResult:  # type: ignore[override]
        if err := _check_credentials():
            return ToolResult(success=False, error=err)
        try:
            data = await _post(f"dns/delete/{domain}/{record_id}")
            if data.get("status") != "SUCCESS":
                return ToolResult(success=False, error=data.get("message", "Unknown error"))
            return ToolResult(
                success=True,
                output=f"Deleted DNS record {record_id} from {domain}",
                data={"domain": domain, "record_id": record_id},
            )
        except Exception as e:
            logger.error("porkbun_delete_dns_record failed for %s: %s", domain, e)
            return ToolResult(success=False, error=str(e))


# ---------------------------------------------------------------------------
# Tool: Ping / verify API credentials
# ---------------------------------------------------------------------------


class PingTool(BaseTool):
    """Verify Porkbun API credentials are valid."""

    name = "porkbun_ping"
    description = "Verify that the Porkbun API credentials are valid and the API is reachable."

    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> ToolResult:
        if err := _check_credentials():
            return ToolResult(success=False, error=err)
        try:
            data = await _post("ping")
            if data.get("status") != "SUCCESS":
                return ToolResult(success=False, error=data.get("message", "Ping failed"))
            ip = data.get("yourIp", "?")
            return ToolResult(
                success=True,
                output=f"Porkbun API is reachable. Your IP: {ip}",
                data={"ip": ip, "credentials_valid": data.get("credentialsValid", False)},
            )
        except Exception as e:
            logger.error("porkbun_ping failed: %s", e)
            return ToolResult(success=False, error=str(e))


# ---------------------------------------------------------------------------
# Tool: Domain health check (bulk NS audit)
# ---------------------------------------------------------------------------


class DomainHealthCheckTool(BaseTool):
    """Check NS delegation status for all domains — identify which need Cloudflare migration."""

    name = "porkbun_domain_health_check"
    description = (
        "Audit all domains in the account and report which are delegated to "
        "Cloudflare vs still on Porkbun defaults. Useful for identifying "
        "domains that need NS migration for Cloudflare Tunnel routing."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> ToolResult:
        if err := _check_credentials():
            return ToolResult(success=False, error=err)
        try:
            # Get all domains
            list_data = await _post("domain/listAll")
            if list_data.get("status") != "SUCCESS":
                return ToolResult(
                    success=False, error=list_data.get("message", "Failed to list domains")
                )

            domains = list_data.get("domains", [])
            active = [d for d in domains if d["status"] == "ACTIVE"]

            cloudflare = []
            porkbun = []
            other = []
            errors = []

            for d in active:
                dom = d["domain"]
                try:
                    ns_data = await _post(f"domain/getNs/{dom}")
                    ns_list = ns_data.get("ns", [])
                    if any("cloudflare" in n for n in ns_list):
                        cloudflare.append(dom)
                    elif any("porkbun" in n for n in ns_list):
                        porkbun.append(dom)
                    elif not ns_list:
                        other.append(f"{dom} (no NS)")
                    else:
                        other.append(f"{dom} ({', '.join(ns_list)})")
                except Exception as e:
                    errors.append(f"{dom}: {e}")

            lines = [
                f"Active domains: {len(active)}",
                f"\nCloudflare ({len(cloudflare)}):",
                *[f"  ✓ {d}" for d in sorted(cloudflare)],
                f"\nPorkbun defaults ({len(porkbun)}) — NEED MIGRATION:",
                *[f"  ✗ {d}" for d in sorted(porkbun)],
            ]
            if other:
                lines.extend([f"\nOther ({len(other)}):", *[f"  ? {d}" for d in sorted(other)]])
            if errors:
                lines.extend([f"\nErrors ({len(errors)}):", *[f"  ! {e}" for e in errors]])

            return ToolResult(
                success=True,
                output="\n".join(lines),
                data={
                    "cloudflare": cloudflare,
                    "porkbun": porkbun,
                    "other": other,
                    "errors": errors,
                },
            )
        except Exception as e:
            logger.error("porkbun_domain_health_check failed: %s", e)
            return ToolResult(success=False, error=str(e))


# ---------------------------------------------------------------------------
# Registry helper
# ---------------------------------------------------------------------------


def get_dns_tools() -> list[BaseTool]:
    """Return all Porkbun DNS tools for registration in the tool registry."""
    return [
        PingTool(),
        ListDomainsTool(),
        GetNameserversTool(),
        UpdateNameserversTool(),
        ListDnsRecordsTool(),
        CreateDnsRecordTool(),
        DeleteDnsRecordTool(),
        DomainHealthCheckTool(),
        ListUrlForwardingTool(),
        DeleteUrlForwardingTool(),
    ]


# ---------------------------------------------------------------------------
# Porkbun URL forwarding (read + delete)
# ---------------------------------------------------------------------------
#
# Porkbun offers a built-in HTTP redirect service via ALIAS + CNAME into
# uixie.porkbun.com. After migrating NS to Cloudflare, these forwards
# become dead weight — CF owns the redirect. These two tools let an agent
# clean them up as part of the migration flow.


class ListUrlForwardingTool(BaseTool):
    """List Porkbun URL forwarding entries for a domain."""

    name = "porkbun_list_url_forwarding"
    description = (
        "List the URL-forwarding entries a domain has configured in Porkbun. "
        "Each entry has an id, subdomain, location (target), type, includePath, "
        "and wildcard flag. Used primarily to find the id of a forward that "
        "needs to be deleted."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Apex domain (e.g. 'example.com').",
                },
            },
            "required": ["domain"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        err = _check_credentials()
        if err:
            return ToolResult(success=False, error=err)
        domain = kwargs["domain"]
        try:
            resp = await _post(f"domain/getUrlForwarding/{domain}")
            if resp.get("status") != "SUCCESS":
                return ToolResult(
                    success=False,
                    error=f"porkbun: {resp.get('message') or resp}",
                )
            forwards = resp.get("forwards") or []
            return ToolResult(
                success=True,
                output=f"Found {len(forwards)} forward(s) for {domain}.",
                data={"forwards": forwards},
            )
        except Exception as e:
            logger.error("porkbun_list_url_forwarding failed: %s", e)
            return ToolResult(success=False, error=str(e))


class DeleteUrlForwardingTool(BaseTool):
    """Delete a single URL-forwarding entry from a domain."""

    name = "porkbun_delete_url_forwarding"
    description = (
        "Delete a URL-forwarding entry on a Porkbun domain by its id. Use "
        "porkbun_list_url_forwarding to look the id up. Typically invoked "
        "as the last step of an NS-migration to Cloudflare: once CF owns "
        "the redirect, the Porkbun-side forward is redundant."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
                "forward_id": {
                    "type": "string",
                    "description": "Id of the forward entry to delete.",
                },
            },
            "required": ["domain", "forward_id"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        err = _check_credentials()
        if err:
            return ToolResult(success=False, error=err)
        domain = kwargs["domain"]
        fid = kwargs["forward_id"]
        try:
            resp = await _post(f"domain/deleteUrlForward/{domain}/{fid}")
            if resp.get("status") != "SUCCESS":
                return ToolResult(
                    success=False,
                    error=f"porkbun: {resp.get('message') or resp}",
                )
            return ToolResult(
                success=True,
                output=f"Deleted URL forward {fid} on {domain}.",
                data={"domain": domain, "forward_id": fid},
            )
        except Exception as e:
            logger.error("porkbun_delete_url_forwarding failed: %s", e)
            return ToolResult(success=False, error=str(e))


# Audience tagging — platform-only tools. Tenant swarms are filtered
# out of these at spec-generation time by ToolRegistry.get_specs(audience=...).
for _cls in (
    ListDomainsTool,
    GetNameserversTool,
    UpdateNameserversTool,
    ListDnsRecordsTool,
    CreateDnsRecordTool,
    DeleteDnsRecordTool,
    PingTool,
    DomainHealthCheckTool,
    ListUrlForwardingTool,
    DeleteUrlForwardingTool,
):
    _cls.audience = Audience.PLATFORM
