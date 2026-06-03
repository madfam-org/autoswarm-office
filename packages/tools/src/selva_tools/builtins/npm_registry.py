"""NPM Registry management tools for the Selva Swarm.

Manages the npm.madfam.io Verdaccio private registry:
- Token lifecycle (create, rotate, check expiry)
- GitHub secret propagation across ecosystem repos
- Proactive expiry monitoring

Auth: Verdaccio htpasswd via NPM_REGISTRY_USER + NPM_REGISTRY_PASSWORD env vars.
Registry: https://npm.madfam.io

NOTE: Token TTL is configured in Verdaccio configmap (currently 29d → should be 365d).
All ecosystem CI/CD depends on NPM_MADFAM_TOKEN being valid.
"""

from __future__ import annotations

import logging
import os
import subprocess
from datetime import UTC, datetime
from typing import Any

import httpx

from ..audience import Audience
from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

NPM_REGISTRY_URL = os.environ.get("NPM_REGISTRY_URL", "https://npm.madfam.io")
NPM_REGISTRY_USER = os.environ.get("NPM_REGISTRY_USER", "")
NPM_REGISTRY_PASSWORD = os.environ.get("NPM_REGISTRY_PASSWORD", "")

# All repos that depend on NPM_MADFAM_TOKEN
ECOSYSTEM_REPOS = [
    "karafiel",
    "enclii",
    "janua",
    "dhanam",
    "tezca",
    "forgesight",
    "fortuna",
    "phynd-crm",
    "avala",
    "digifab-quoting",
    "forj",
    "rondelio",
    "routecraft",
    "blueprint-harvester",
    "sim4d",
    "madfam-site",
    "selva-office",
    "solarpunk-foundry",
    "symbiosis-hcm",
    "stratum-tcg",
    "primavera3d",
]
GITHUB_ORG = "madfam-org"


def _decode_jwt_expiry(token: str) -> datetime | None:
    """Decode JWT expiry without verification (for monitoring only)."""
    import base64
    import json

    try:
        payload = token.split(".")[1]
        # Add padding
        payload += "=" * (4 - len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload))
        exp = decoded.get("exp")
        if exp:
            return datetime.fromtimestamp(exp, tz=UTC)
    except Exception:
        pass
    return None


class NpmCheckExpiryTool(BaseTool):
    """Check when the current NPM registry token expires."""

    name = "selva_npm_check_expiry"
    description = (
        "Check the expiry date of the current npm.madfam.io token. "
        "Alerts if token expires within 30 days. Safe to call anytime."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> ToolResult:
        # Check local .npmrc token
        npmrc_path = os.path.expanduser("~/.npmrc")
        token = ""
        try:
            with open(npmrc_path) as f:
                for line in f:
                    if "npm.madfam.io/:_authToken=" in line:
                        token = line.split("=", 1)[1].strip()
                        break
        except FileNotFoundError:
            return ToolResult(success=False, error="~/.npmrc not found")

        if not token:
            return ToolResult(success=False, error="No npm.madfam.io token in ~/.npmrc")

        # Decode expiry
        expiry = _decode_jwt_expiry(token)
        if not expiry:
            return ToolResult(success=False, error="Cannot decode token expiry")

        now = datetime.now(UTC)
        days_left = (expiry - now).days
        is_expired = days_left < 0
        needs_rotation = days_left < 30

        # Verify token actually works
        token_valid = False
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{NPM_REGISTRY_URL}/-/whoami",
                    headers={"Authorization": f"Bearer {token}"},
                )
                token_valid = resp.status_code == 200
        except Exception:
            pass

        status = "EXPIRED" if is_expired else ("ROTATION NEEDED" if needs_rotation else "HEALTHY")
        output = (
            f"NPM Token Status: {status}\n"
            f"  Registry: {NPM_REGISTRY_URL}\n"
            f"  Expires: {expiry.isoformat()}\n"
            f"  Days remaining: {days_left}\n"
            f"  API valid: {token_valid}"
        )

        return ToolResult(
            success=True,
            output=output,
            data={
                "status": status,
                "expires_at": expiry.isoformat(),
                "days_remaining": days_left,
                "is_expired": is_expired,
                "needs_rotation": needs_rotation,
                "api_valid": token_valid,
            },
        )


class NpmCreateTokenTool(BaseTool):
    """Create a fresh NPM registry token by authenticating to Verdaccio."""

    name = "selva_npm_create_token"
    description = (
        "Authenticate to npm.madfam.io and get a fresh JWT token. "
        "Requires NPM_REGISTRY_USER and NPM_REGISTRY_PASSWORD env vars. "
        "Requires approval."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not NPM_REGISTRY_USER or not NPM_REGISTRY_PASSWORD:
            return ToolResult(
                success=False,
                error="NPM_REGISTRY_USER and NPM_REGISTRY_PASSWORD must be set",
            )

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{NPM_REGISTRY_URL}/-/verdaccio/sec/login",
                    json={
                        "username": NPM_REGISTRY_USER,
                        "password": NPM_REGISTRY_PASSWORD,
                    },
                )
                data = resp.json()

            token = data.get("token")
            if not token:
                return ToolResult(success=False, error=f"Login failed: {data}")

            expiry = _decode_jwt_expiry(token)
            exp_str = expiry.isoformat() if expiry else "unknown"

            logger.info("NPM token created for %s, expires %s", NPM_REGISTRY_USER, exp_str)
            return ToolResult(
                success=True,
                output=f"Token created for {NPM_REGISTRY_USER} (expires: {exp_str})",
                data={"token": token, "expires_at": exp_str, "user": NPM_REGISTRY_USER},
            )
        except Exception as e:
            logger.error("NPM token creation failed: %s", e)
            return ToolResult(success=False, error=str(e))


class NpmRotateTokenTool(BaseTool):
    """Rotate the NPM token: create new, update ~/.npmrc and GitHub secrets."""

    name = "selva_npm_rotate_token"
    description = (
        "Full token rotation: authenticate to Verdaccio, update ~/.npmrc, "
        "and propagate new token to all ecosystem GitHub repos as NPM_MADFAM_TOKEN. "
        "Requires approval."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repos": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Repos to update (default: all ecosystem repos)",
                },
            },
            "required": [],
        }

    async def execute(self, *, repos: list[str] | None = None, **kwargs: Any) -> ToolResult:
        if not NPM_REGISTRY_USER or not NPM_REGISTRY_PASSWORD:
            return ToolResult(
                success=False,
                error="NPM_REGISTRY_USER and NPM_REGISTRY_PASSWORD must be set",
            )

        target_repos = repos or ECOSYSTEM_REPOS
        results: dict[str, Any] = {"created": False, "npmrc_updated": False, "repos": {}}

        # Step 1: Get fresh token
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{NPM_REGISTRY_URL}/-/verdaccio/sec/login",
                    json={
                        "username": NPM_REGISTRY_USER,
                        "password": NPM_REGISTRY_PASSWORD,
                    },
                )
                data = resp.json()

            token = data.get("token")
            if not token:
                return ToolResult(success=False, error=f"Login failed: {data}")

            results["created"] = True
            expiry = _decode_jwt_expiry(token)
            results["expires_at"] = expiry.isoformat() if expiry else "unknown"
        except Exception as e:
            return ToolResult(success=False, error=f"Token creation failed: {e}")

        # Step 2: Update ~/.npmrc
        try:
            npmrc_path = os.path.expanduser("~/.npmrc")
            lines = []
            updated = False
            try:
                with open(npmrc_path) as f:
                    for line in f:
                        if "npm.madfam.io/:_authToken=" in line:
                            lines.append(f"//npm.madfam.io/:_authToken={token}\n")
                            updated = True
                        else:
                            lines.append(line)
            except FileNotFoundError:
                lines = [f"//npm.madfam.io/:_authToken={token}\n"]
                updated = True

            if not updated:
                lines.append(f"//npm.madfam.io/:_authToken={token}\n")

            with open(npmrc_path, "w") as f:
                f.writelines(lines)

            results["npmrc_updated"] = True
        except Exception as e:
            results["npmrc_error"] = str(e)

        # Step 3: Update GitHub secrets
        for repo in target_repos:
            try:
                proc = subprocess.run(
                    [
                        "gh",
                        "secret",
                        "set",
                        "NPM_MADFAM_TOKEN",
                        "--repo",
                        f"{GITHUB_ORG}/{repo}",
                        "--body",
                        token,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                results["repos"][repo] = "OK" if proc.returncode == 0 else proc.stderr.strip()
            except Exception as e:
                results["repos"][repo] = str(e)

        success_count = sum(1 for v in results["repos"].values() if v == "OK")
        output = (
            f"Token rotated successfully\n"
            f"  User: {NPM_REGISTRY_USER}\n"
            f"  Expires: {results['expires_at']}\n"
            f"  ~/.npmrc: {'updated' if results['npmrc_updated'] else 'FAILED'}\n"
            f"  GitHub repos: {success_count}/{len(target_repos)} updated"
        )

        logger.info("NPM token rotated: %d/%d repos updated", success_count, len(target_repos))
        return ToolResult(success=True, output=output, data=results)


class NpmUpdateGitHubSecretsTool(BaseTool):
    """Update NPM_MADFAM_TOKEN in GitHub repos using a provided token."""

    name = "selva_npm_update_github_secrets"
    description = (
        "Update NPM_MADFAM_TOKEN secret in specified GitHub repos. "
        "Uses the current ~/.npmrc token unless a token is provided. "
        "Requires approval."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "token": {
                    "type": "string",
                    "description": "Token to set (default: read from ~/.npmrc)",
                },
                "repos": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Repos to update (default: all ecosystem repos)",
                },
            },
            "required": [],
        }

    async def execute(
        self, *, token: str | None = None, repos: list[str] | None = None, **kwargs: Any
    ) -> ToolResult:
        # Get token from ~/.npmrc if not provided
        if not token:
            try:
                with open(os.path.expanduser("~/.npmrc")) as f:
                    for line in f:
                        if "npm.madfam.io/:_authToken=" in line:
                            token = line.split("=", 1)[1].strip()
                            break
            except FileNotFoundError:
                pass

        if not token:
            return ToolResult(success=False, error="No token provided and none found in ~/.npmrc")

        target_repos = repos or ECOSYSTEM_REPOS
        results: dict[str, str] = {}

        for repo in target_repos:
            try:
                proc = subprocess.run(
                    [
                        "gh",
                        "secret",
                        "set",
                        "NPM_MADFAM_TOKEN",
                        "--repo",
                        f"{GITHUB_ORG}/{repo}",
                        "--body",
                        token,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                results[repo] = "OK" if proc.returncode == 0 else proc.stderr.strip()
            except Exception as e:
                results[repo] = str(e)

        success_count = sum(1 for v in results.values() if v == "OK")
        output = f"Updated {success_count}/{len(target_repos)} repos"

        return ToolResult(
            success=success_count == len(target_repos),
            output=output,
            data={"results": results, "success_count": success_count},
        )


def get_npm_registry_tools() -> list[BaseTool]:
    """Return all NPM registry tools for registration in the tool registry."""
    return [
        NpmCheckExpiryTool(),
        NpmCreateTokenTool(),
        NpmRotateTokenTool(),
        NpmUpdateGitHubSecretsTool(),
    ]


# Audience tagging — platform-only tools. Tenant swarms are filtered
# out of these at spec-generation time by ToolRegistry.get_specs(audience=...).
for _cls in (
    NpmCheckExpiryTool,
    NpmCreateTokenTool,
    NpmRotateTokenTool,
    NpmUpdateGitHubSecretsTool,
):
    _cls.audience = Audience.PLATFORM
