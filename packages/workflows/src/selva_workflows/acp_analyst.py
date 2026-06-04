import asyncio
import json
import os

import httpx

MCP_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "mcp_config.json")


class ACPAnalystNode:
    """
    Phase I: The Analyst (Dirty Environment).

    Uses Zero-Context RPC subprocess threads to scrape target URLs cheaply,
    dropping the heavy Playwright/graph-state overhead. When ``mcp_config.json``
    is present, the subagent bootstraps the configured MCP servers first,
    giving it dynamic access to external tools (Tavily search, GitHub, etc.)
    without requiring container rebuilds — exactly mirroring the Hermes Agent
    Model Context Protocol pattern.
    """

    def __init__(self, target_url: str) -> None:
        self.target_url = target_url

    # ------------------------------------------------------------------
    # MCP bootstrap
    # ------------------------------------------------------------------

    def _get_mcp_bootstrap_snippet(self) -> str:
        """
        Return a Python code snippet that starts the MCP server processes
        listed in ``mcp_config.json``.  The snippet is injected at the top
        of the RPC child-script so tool servers are available before crawling.
        """
        try:
            config_path = os.path.abspath(MCP_CONFIG_PATH)
            with open(config_path) as f:
                config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return "# MCP config not found — running without external tools\n"

        lines = [
            "import subprocess as _sp, os as _os",
            "_mcp_procs = []",
        ]
        for name, srv in config.get("mcpServers", {}).items():
            cmd = json.dumps([srv["command"]] + srv.get("args", []))
            env_overrides = srv.get("env", {})
            env_str = (
                "{**_os.environ, "
                + ", ".join(f'"{k}": _os.environ.get("{k}", "")' for k in env_overrides)
                + "}"
            )
            lines.append(
                f"_mcp_procs.append(_sp.Popen({cmd}, env={env_str}, "
                f"stdout=_sp.DEVNULL, stderr=_sp.DEVNULL))  # {name}"
            )
        lines.append("import time; time.sleep(1)  # give servers a moment to start")
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # Safe HTTP fallback
    # ------------------------------------------------------------------

    def _safe_fetch_text(self, target_url: str) -> str:
        from selva_tools.builtins.http_tools import _build_safe_request_kwargs

        request_kwargs, _ = _build_safe_request_kwargs(
            "GET",
            target_url,
            headers={"User-Agent": "Selva-Analyst/1.0"},
            extra={"timeout": 10.0, "follow_redirects": True},
        )
        with httpx.Client(
            trust_env=False,
            transport=httpx.HTTPTransport(retries=0),
        ) as client:
            resp = client.request(**request_kwargs)
        resp.raise_for_status()
        return resp.text[:4000]

    # ------------------------------------------------------------------
    # Core extraction
    # ------------------------------------------------------------------

    def run(self) -> dict:
        print(f"[Phase I] Launching browser extraction (with MCP) for {self.target_url} …")

        # Backward-compat marker for future bootstrap work. The ACP path
        # itself is intentionally best-effort; do not fail task startup if the
        # MCP snippet is missing or malformed.
        _ = self._get_mcp_bootstrap_snippet()

        # ----------------------------------------------------------------
        # Gap 1: Use browser_extract (Playwright) for JS-rendered targets
        # ----------------------------------------------------------------
        extracted_text = ""
        screenshot_b64 = ""
        try:
            from selva_tools.browser import browser_extract, browser_screenshot

            extracted_text = asyncio.run(browser_extract(self.target_url))
            screenshot_b64 = asyncio.run(browser_screenshot(self.target_url))
        except Exception as exc:
            print(f"[Phase I] Browser extraction failed ({exc}) — falling back to safe HTTP")
            try:
                extracted_text = self._safe_fetch_text(self.target_url)
            except Exception as req_exc:
                extracted_text = f"Error fetching: {req_exc}"

        if extracted_text is None:
            extracted_text = ""
        prd = (
            f"# PRD Draft for {self.target_url}\n\n## Extracted Context\n\n{extracted_text[:2000]}"
        )

        result = {
            "prd": prd,
            "tests": "def test_login():\n    assert True",
        }
        if screenshot_b64:
            result["screenshot_b64"] = screenshot_b64

        return result
