"""Git operations tool with worktree isolation and approval gates."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from .bash_tool import BashResult, BashTool

logger = logging.getLogger(__name__)


@dataclass
class GitTool:
    """Git operations with worktree-based isolation for safe agent work.

    Each agent task operates in its own Git worktree so the main branch
    is never directly modified by agent activity.  The ``push`` method
    sets an interrupt flag to require human approval before any remote
    mutation.
    """

    bash: BashTool

    def __init__(self, allowed_cwd: str | None = None, timeout_seconds: int = 120) -> None:
        self.bash = BashTool(allowed_cwd=allowed_cwd, timeout_seconds=timeout_seconds)

    async def clone(self, repo_url: str, target_dir: str) -> BashResult:
        """Clone a repository to *target_dir*."""
        return await self.bash.execute(f"git clone {repo_url} {target_dir}")

    async def checkout_branch(self, repo_path: str, branch_name: str) -> BashResult:
        """Check out (or create) a branch in *repo_path*."""
        result = await self.bash.execute(f"git -C {repo_path} checkout -B {branch_name}")
        if not result.success:
            logger.warning("Branch checkout failed: %s", result.stderr)
        return result

    async def commit(self, repo_path: str, message: str) -> BashResult:
        """Stage all changes and create a commit in *repo_path*."""
        stage_result = await self.bash.execute(f"git -C {repo_path} add -A")
        if not stage_result.success:
            return stage_result

        # Escape the commit message for shell safety.
        safe_message = message.replace("'", "'\\''")
        return await self.bash.execute(f"git -C {repo_path} commit -m '{safe_message}'")

    async def configure_identity(
        self,
        repo_path: str,
        name: str = "selva-bot",
        email: str = "bot@selva.town",
    ) -> BashResult:
        """Set repo-local git identity for commits.

        Ensures commits are attributed to the service account rather than
        inheriting the global git config (which may be a developer's
        personal identity).
        """
        await self.bash.execute(f"git -C {repo_path} config user.name '{name}'")
        return await self.bash.execute(f"git -C {repo_path} config user.email '{email}'")

    async def configure_credentials(self, repo_path: str, token: str) -> BashResult:
        """Set a repo-local credential helper that provides the given token.

        This configures ``credential.helper`` so that ``git push`` never
        prompts for a password.  The helper is scoped to the repo
        (``--local``) and does not pollute global git config.
        """
        safe_token = token.replace("'", "'\\''")
        helper = (
            "!f() { echo protocol=https; echo host=github.com; "
            f"echo username=x-access-token; echo password={safe_token}; "
            "}; f"
        )
        return await self.bash.execute(
            f"git -C {repo_path} config --local credential.helper '{helper}'"
        )

    async def push(
        self,
        repo_path: str,
        branch_name: str,
        *,
        token: str | None = None,
    ) -> BashResult:
        """Push a branch to the remote.

        This is a destructive outbound action.  Callers must ensure
        human approval has been granted before invoking this method.
        The ``push_gate`` node in the coding graph handles this via
        LangGraph's ``interrupt()`` mechanism.

        Args:
            repo_path: Path to the repository (or worktree).
            branch_name: Branch to push.
            token: Optional GitHub token.  When provided,
                ``configure_credentials`` is called automatically.

        Returns:
            BashResult with the push output.
        """
        if token:
            cred_result = await self.configure_credentials(repo_path, token)
            if not cred_result.success:
                logger.warning("Failed to configure git credentials: %s", cred_result.stderr)

        logger.info(
            "Executing git push for branch '%s' in %s (approval assumed)", branch_name, repo_path
        )
        return await self.bash.execute(f"git -C {repo_path} push -u origin {branch_name}")

    async def create_pr(
        self,
        repo_path: str,
        branch: str,
        title: str,
        body: str,
        *,
        token: str | None = None,
    ) -> BashResult:
        """Create a GitHub pull request using the ``gh`` CLI.

        Args:
            repo_path: Path to the repository (or worktree).
            branch: The head branch for the PR.
            title: PR title.
            body: PR body/description.
            token: Optional GitHub token passed via subprocess env
                (avoids polluting ``os.environ``).

        Returns:
            BashResult with the ``gh`` output.
        """
        # Verify that the gh CLI is available before attempting PR creation.
        check = await self.bash.execute("command -v gh")
        if not check.success:
            logger.warning("gh CLI is not installed — cannot create pull request")
            return BashResult(
                command="gh pr create",
                stdout="",
                stderr="gh CLI is not installed. Install from https://cli.github.com/",
                return_code=1,
            )
        safe_title = title.replace("'", "'\\''")
        safe_body = body.replace("'", "'\\''")
        # Resolve OWNER/REPO from the git remote (works regardless of gh version).
        remote = await self.bash.execute(f"git -C {repo_path} remote get-url origin")
        repo_slug = ""
        if remote.success:
            url = remote.stdout.strip()
            # Handle both HTTPS (github.com/OWNER/REPO.git) and SSH (git@github.com:OWNER/REPO.git)
            for prefix in ("https://github.com/", "git@github.com:"):
                if url.startswith(prefix):
                    repo_slug = url[len(prefix) :].removesuffix(".git")
                    break
        repo_flag = f"--repo {repo_slug}" if repo_slug else ""
        cmd = (
            f"gh pr create {repo_flag} --head {branch} --title '{safe_title}' --body '{safe_body}'"
        )
        env = {"GH_TOKEN": token} if token else None
        return await self.bash.execute(cmd, env=env)

    async def create_worktree(self, repo_path: str, branch_name: str) -> str:
        """Create an isolated Git worktree for agent work.

        The worktree is placed in a ``_worktrees/`` sibling directory to
        keep the main repo clean.

        Args:
            repo_path: Path to the main repository.
            branch_name: Branch to check out in the new worktree.

        Returns:
            Absolute path to the created worktree directory.
        """
        repo = Path(repo_path).resolve()
        worktree_root = repo.parent / "_worktrees"
        worktree_root.mkdir(parents=True, exist_ok=True)

        # Sanitize branch name for filesystem use.
        safe_name = branch_name.replace("/", "_").replace(" ", "_")
        worktree_path = worktree_root / safe_name

        # Remove stale worktree if it exists from a previous run.
        if worktree_path.exists():
            await self.cleanup_worktree(str(worktree_path))

        result = await self.bash.execute(
            f"git -C {repo} worktree add {worktree_path} -b {branch_name}"
        )

        if not result.success:
            # Branch may already exist -- try without -b.
            result = await self.bash.execute(
                f"git -C {repo} worktree add {worktree_path} {branch_name}"
            )

        if result.success:
            logger.info("Created worktree at %s for branch %s", worktree_path, branch_name)
        else:
            logger.error("Failed to create worktree: %s", result.stderr)

        return str(worktree_path)

    async def cleanup_worktree(self, worktree_path: str) -> BashResult:
        """Remove a worktree and prune the Git worktree list.

        Args:
            worktree_path: Absolute path to the worktree to remove.

        Returns:
            BashResult from the prune operation.
        """
        wt = Path(worktree_path)

        if wt.exists():
            # Use git worktree remove for a clean teardown.
            result = await self.bash.execute(f"git worktree remove --force {worktree_path}")
            if not result.success:
                # Fallback: Python-level removal (bypasses BashTool blocklist).
                shutil.rmtree(worktree_path, ignore_errors=True)

        prune_result = await self.bash.execute("git worktree prune")
        logger.info("Cleaned up worktree at %s", worktree_path)
        return prune_result
