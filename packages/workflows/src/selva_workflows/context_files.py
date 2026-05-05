"""
Gap 5: Project Context Files — AGENTS.md / .autoswarm.md loader

Scans a workspace root for project-level context files and injects them
into ACP system prompts, mirroring Hermes Agent's AGENTS.md / .hermes.md
convention for per-project grounding.

A1: Prompt injection detection — scans loaded content for jailbreak patterns.
A2: @context_ref expansion — inline file references resolved at load time.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Files scanned in priority order (later files take precedence)
_CONTEXT_SOURCES = [
    "CLAUDE.md",  # Cross-tool compatibility (read-only passthrough)
    "GEMINI.md",  # Cross-tool compatibility
    "AGENTS.md",  # Project-level architecture / agent instructions
    ".autoswarm.md",  # Workspace-local override (highest priority)
]

_MAX_CHARS_PER_FILE = 32_000  # ~8,000 tokens at 4 chars/token

# A1: Prompt injection signatures (case-insensitive)
_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"ignore (all )?previous instructions?",
        r"disregard (all )?previous",
        r"forget (everything|all) (above|before)",
        r"</?system>",
        r"\[INST\]|\[/INST\]",
        r"new system prompt",
        r"act as (a |an )?DAN",
        r"jailbreak",
        r"prompt injection",
        r"you are now\.* unrestricted",
        r"override (safety|security|guidelines)",
        r"\\x[0-9a-f]{2}",  # Hex escape attempts
    ]
]

# A2: @context_ref pattern — matches @relative/path/to/file.ext
_CONTEXT_REF_RE = re.compile(r"@([\w./\-]+\.\w+)")


class ContextFileLoader:
    """
    Scans a workspace root for AutoSwarm-compatible context files and
    returns their concatenated content for injection into system prompts.

    A1: Scans each file for prompt-injection patterns before inclusion.
    A2: Expands @context_ref inline references to other files.
    """

    def __init__(
        self,
        max_chars_per_file: int = _MAX_CHARS_PER_FILE,
        injection_policy: str | None = None,
    ) -> None:
        self._max_chars = max_chars_per_file
        # Policy: 'block' | 'strip' | 'warn'. Reads env var if not provided.
        self._policy = injection_policy or os.environ.get("AUTOSWARM_INJECTION_POLICY", "warn")

    def load_context(self, workspace_path: str) -> str:
        """
        Scan *workspace_path* for context files and return their contents.

        Returns:
            Formatted context string ready for injection into a system prompt,
            or empty string if no context files are found.
        """
        root = Path(workspace_path)
        if not root.exists() or not root.is_dir():
            logger.debug("ContextFileLoader: workspace %s does not exist.", workspace_path)
            return ""

        sections: list[str] = []
        for filename in _CONTEXT_SOURCES:
            path = root / filename
            if path.exists() and path.is_file():
                content = self._read_file(path)
                if not content:
                    continue
                # A2: Expand @context_ref inline references
                content = self._expand_refs(content, root)
                # A1: Injection scan — returns ``None`` to signal "blocked"
                scanned = self._scan_injection(filename, content)
                if scanned is None:  # blocked
                    continue
                sections.append(f"## [{filename}]\n\n{scanned}")

        if not sections:
            return ""

        combined = "\n\n---\n\n".join(sections)
        logger.info(
            "ContextFileLoader: injected %d context file(s) from %s (%d chars total).",
            len(sections),
            workspace_path,
            len(combined),
        )
        return combined

    # ------------------------------------------------------------------
    # A1 — Prompt injection detection
    # ------------------------------------------------------------------

    def _scan_injection(self, filename: str, text: str) -> str | None:
        """
        Scan *text* for prompt injection patterns.
        Returns (possibly modified) text, or None if the file is blocked.
        """
        matches = [p.pattern for p in _INJECTION_PATTERNS if p.search(text)]
        if not matches:
            return text

        logger.warning(
            "ContextFileLoader: potential prompt injection in %s (patterns: %s)",
            filename,
            ", ".join(matches[:3]),
        )
        if self._policy == "block":
            logger.error("ContextFileLoader: BLOCKED %s due to injection policy=block.", filename)
            return None
        if self._policy == "strip":
            for pat in _INJECTION_PATTERNS:
                text = pat.sub("[REDACTED]", text)
            return text
        # policy == 'warn' (default) — include as-is but log
        return text

    # ------------------------------------------------------------------
    # A2 — @context_ref inline expansion
    # ------------------------------------------------------------------

    def _expand_refs(self, text: str, root: Path, _depth: int = 0) -> str:
        """
        Replace @relative/path/file.ext references with file contents.
        Limits recursion to 3 levels to prevent circular includes.
        """
        if _depth >= 3:
            return text

        def _replacer(m: re.Match) -> str:
            ref_path = root / m.group(1)
            if not ref_path.exists() or not ref_path.is_file():
                logger.debug("ContextFileLoader: @ref not found: %s", ref_path)
                return m.group(0)  # Leave as-is if missing
            try:
                content = ref_path.read_text(encoding="utf-8", errors="replace").strip()
                if len(content) > 8_000:
                    content = content[:8_000] + "\n[... truncated ...]"
                # Recurse into the referenced file
                content = self._expand_refs(content, root, _depth + 1)
                return f"\n\n### @{m.group(1)}\n\n{content}\n\n"
            except Exception as exc:
                logger.warning("ContextFileLoader: could not expand @ref %s: %s", ref_path, exc)
                return m.group(0)

        return _CONTEXT_REF_RE.sub(_replacer, text)

    def _read_file(self, path: Path) -> str:
        """Read a file, truncating at _max_chars with a warning if needed."""
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            if len(text) > self._max_chars:
                logger.warning(
                    "ContextFileLoader: %s exceeds %d chars — truncating.",
                    path.name,
                    self._max_chars,
                )
                text = (
                    text[: self._max_chars] + "\n\n[... truncated — file exceeds token limit ...]"
                )
            return text
        except Exception as exc:
            logger.error("ContextFileLoader: could not read %s: %s", path, exc)
            return ""
