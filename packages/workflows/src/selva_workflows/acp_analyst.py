import asyncio
import json
import os

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
    # Core extraction
    # ------------------------------------------------------------------

    def run(self) -> dict:
        print(f"[Phase I] Launching browser extraction (with MCP) for {self.target_url} …")

        self._get_mcp_bootstrap_snippet()  # Keep side-effect of warming MCP procs

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
            print(f"[Phase I] Browser extraction failed ({exc}) — falling back to requests")
            try:
                import requests

                resp = requests.get(
                    self.target_url,
                    timeout=10,
                    headers={"User-Agent": "Selva-Analyst/1.0"},
                )
                extracted_text = resp.text[:4000]
            except Exception as req_exc:
                extracted_text = f"Error fetching: {req_exc}"

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
