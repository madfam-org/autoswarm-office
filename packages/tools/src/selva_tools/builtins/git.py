"""Git operation tools: commit, push, diff, branch, create PR."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..base import BaseTool, ToolResult
from ..sandbox import ToolSandbox

# Conventional commits prefix pattern — the loose form used across MADFAM repos.
# Accepts optional scope and optional `!` for breaking changes.
_CONVENTIONAL_PREFIX = re.compile(
    r"^(feat|fix|docs|style|refactor|test|chore|ci|perf|build|revert)"
    r"(\([\w\-.]+\))?!?:\s.+"
)

_PROTECTED_BRANCHES = frozenset({"main", "master", "develop", "trunk"})


class GitCommitTool(BaseTool):
    name = "git_commit"
    description = "Stage files and create a git commit"

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Commit message"},
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Files to stage (empty = all modified)",
                    "default": [],
                },
                "repo_path": {"type": "string", "default": "."},
            },
            "required": ["message"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        message = kwargs.get("message", "")
        files = kwargs.get("files", [])
        repo_path = kwargs.get("repo_path", ".")
        sandbox = ToolSandbox()

        if files:
            add_cmd = ["git", "-C", repo_path, "add", *files]
        else:
            add_cmd = ["git", "-C", repo_path, "add", "-A"]

        add_result = await sandbox.run_command(add_cmd, timeout=30.0)
        if not add_result["success"]:
            return ToolResult(success=False, error=add_result["stderr"])

        result = await sandbox.run_command(
            ["git", "-C", repo_path, "commit", "-m", message],
            timeout=30.0,
        )
        if result["success"]:
            return ToolResult(output=result["stdout"])
        return ToolResult(success=False, error=result["stderr"])


class GitPushTool(BaseTool):
    name = "git_push"
    description = "Push commits to the remote repository"

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "branch": {"type": "string", "default": ""},
                "repo_path": {"type": "string", "default": "."},
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        branch = kwargs.get("branch", "")
        repo_path = kwargs.get("repo_path", ".")
        sandbox = ToolSandbox()
        cmd = ["git", "-C", repo_path, "push"]
        if branch:
            cmd.extend(["origin", branch])
        result = await sandbox.run_command(cmd, timeout=60.0)
        if result["success"]:
            return ToolResult(output=result["stdout"])
        return ToolResult(success=False, error=result["stderr"])


class GitDiffTool(BaseTool):
    name = "git_diff"
    description = "Show the current git diff (staged and unstaged changes)"

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "staged": {"type": "boolean", "default": False},
                "repo_path": {"type": "string", "default": "."},
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        staged = kwargs.get("staged", False)
        repo_path = kwargs.get("repo_path", ".")
        sandbox = ToolSandbox()
        cmd = ["git", "-C", repo_path, "diff"]
        if staged:
            cmd.append("--staged")
        result = await sandbox.run_command(cmd, timeout=15.0)
        return ToolResult(output=result["stdout"])


class GitBranchTool(BaseTool):
    name = "git_branch"
    description = "Create, list, or switch git branches"

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "create", "checkout"],
                    "default": "list",
                },
                "name": {"type": "string", "description": "Branch name", "default": ""},
                "repo_path": {"type": "string", "default": "."},
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "list")
        name = kwargs.get("name", "")
        repo_path = kwargs.get("repo_path", ".")
        sandbox = ToolSandbox()

        if action == "list":
            cmd = ["git", "-C", repo_path, "branch", "-a"]
        elif action == "create":
            cmd = ["git", "-C", repo_path, "checkout", "-b", name]
        elif action == "checkout":
            cmd = ["git", "-C", repo_path, "checkout", name]
        else:
            return ToolResult(success=False, error=f"Unknown action: {action}")

        result = await sandbox.run_command(cmd, timeout=15.0)
        if result["success"]:
            return ToolResult(output=result["stdout"])
        return ToolResult(success=False, error=result["stderr"])


class GitCreatePRTool(BaseTool):
    """Create a PR via `gh pr create` with pre-flight validation.

    Unlike shelling out to `gh pr create` directly, this tool:
    - refuses to PR from a protected branch (main/master/develop/trunk)
    - warns when the title doesn't follow conventional commits
    - auto-loads the repo's PR template when the body is empty
    - auto-adds reviewers from .github/CODEOWNERS (when present)

    Returns the created PR's URL in ``data.url``. Fails fast with a
    structured error if any hard validation (protected branch, missing
    gh auth) is violated.
    """

    name = "git_create_pr"
    description = "Create a pull request with safety checks (protected branch, conventional commit title, PR template, CODEOWNERS reviewers)"  # noqa: E501

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "PR title. Warning emitted if not conventional-commit shaped (feat/fix/... prefix).",  # noqa: E501
                },
                "body": {
                    "type": "string",
                    "description": "PR body markdown. If empty, the repo's PR template is used when available.",  # noqa: E501
                    "default": "",
                },
                "base": {
                    "type": "string",
                    "description": "Base branch to PR against.",
                    "default": "main",
                },
                "draft": {"type": "boolean", "default": False},
                "reviewers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Explicit reviewer logins. Merged with CODEOWNERS auto-detection.",  # noqa: E501
                    "default": [],
                },
                "repo_path": {"type": "string", "default": "."},
            },
            "required": ["title"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        title: str = kwargs.get("title", "")
        body: str = kwargs.get("body", "") or ""
        base: str = kwargs.get("base", "main")
        draft: bool = bool(kwargs.get("draft", False))
        reviewers: list[str] = list(kwargs.get("reviewers", []) or [])
        repo_path: str = kwargs.get("repo_path", ".")

        if not title.strip():
            return ToolResult(success=False, error="title is required")

        sandbox = ToolSandbox()
        warnings: list[str] = []

        # 1. Current branch must not be a protected one.
        branch_probe = await sandbox.run_command(
            ["git", "-C", repo_path, "rev-parse", "--abbrev-ref", "HEAD"],
            timeout=5.0,
        )
        if not branch_probe["success"]:
            return ToolResult(
                success=False,
                error=f"could not read current branch: {branch_probe['stderr'].strip()}",
            )
        current_branch = branch_probe["stdout"].strip()
        if current_branch in _PROTECTED_BRANCHES:
            return ToolResult(
                success=False,
                error=(
                    f"refusing to create PR from protected branch '{current_branch}'. "
                    "Check out a feature branch first."
                ),
                data={"current_branch": current_branch},
            )

        # 2. Conventional-commit title advisory.
        if not _CONVENTIONAL_PREFIX.match(title):
            warnings.append(
                "title does not match conventional-commit pattern "
                "(expected 'feat: ...', 'fix(scope): ...', etc.)"
            )

        # 3. PR template fallback when body is empty.
        resolved_body = body
        if not resolved_body.strip():
            template_body = _load_pr_template(Path(repo_path))
            if template_body is not None:
                resolved_body = template_body
                warnings.append("empty body; loaded .github/pull_request_template.md")

        # 4. CODEOWNERS-derived reviewers (additive, deduped).
        codeowner_reviewers = _extract_codeowner_reviewers(Path(repo_path))
        all_reviewers = sorted({*reviewers, *codeowner_reviewers})

        # 5. Build + execute `gh pr create`.
        cmd_parts = [
            "gh",
            "pr",
            "create",
            "--base",
            base,
            "--head",
            current_branch,
            "--title",
            title,
            "--body",
            resolved_body,
        ]
        if draft:
            cmd_parts.append("--draft")
        for reviewer in all_reviewers:
            cmd_parts.extend(["--reviewer", reviewer])

        result = await sandbox.run_command(cmd_parts, cwd=repo_path, timeout=60.0)
        if not result["success"]:
            return ToolResult(
                success=False,
                error=result["stderr"].strip() or "gh pr create failed",
                data={
                    "current_branch": current_branch,
                    "warnings": warnings,
                    "reviewers": all_reviewers,
                },
            )

        url = result["stdout"].strip().splitlines()[-1] if result["stdout"].strip() else ""
        return ToolResult(
            output=url or "PR created",
            data={
                "url": url,
                "current_branch": current_branch,
                "base": base,
                "reviewers": all_reviewers,
                "warnings": warnings,
            },
        )


def _load_pr_template(repo: Path) -> str | None:
    """Return the repo's PR template body, or None if missing."""
    candidates = [
        repo / ".github" / "pull_request_template.md",
        repo / ".github" / "PULL_REQUEST_TEMPLATE.md",
        repo / "docs" / "pull_request_template.md",
    ]
    for path in candidates:
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8")
            except OSError:
                return None
    return None


def _extract_codeowner_reviewers(repo: Path) -> list[str]:
    """Parse CODEOWNERS for @user / @org/team tokens.

    We keep the matching simple — a real CODEOWNERS parser would match
    paths against the diff, but the hard gate is sufficient for a
    pre-flight tool. GitHub itself does the authoritative enforcement.
    """
    candidates = [
        repo / ".github" / "CODEOWNERS",
        repo / "CODEOWNERS",
        repo / "docs" / "CODEOWNERS",
    ]
    path = next((c for c in candidates if c.is_file()), None)
    if path is None:
        return []
    reviewers: set[str] = set()
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            for token in line.split()[1:]:
                if token.startswith("@"):
                    reviewers.add(token.lstrip("@"))
    except OSError:
        return []
    return sorted(reviewers)
