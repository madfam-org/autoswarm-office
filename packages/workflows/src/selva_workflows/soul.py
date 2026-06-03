"""
Next-Tier: SOUL.md Personality System

Mirrors Hermes Agent's SOUL.md — a persistent markdown file that defines
the agent's personality, tone, values, and behavioral constraints.
Injected into every system prompt ahead of Honcho's dynamic behavioral
addendum, giving operators static brand-level control.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_SOUL_PATH = Path.home() / ".selva" / "SOUL.md"
_PROJECT_SOUL_PATH = Path(".selva") / "SOUL.md"
_MAX_CHARS = 8_000


class SoulLoader:
    """
    Loads the agent's SOUL.md personality file.

    Discovery order (first found wins):
    1. ``SELVA_SOUL_PATH`` env var
    2. ``.selva/SOUL.md``  (project-local)
    3. ``~/.selva/SOUL.md``  (user-global)
    """

    def __init__(self) -> None:
        self._cached: str | None = None

    def load(self, force_reload: bool = False) -> str:
        """Return the SOUL.md content, or empty string if none is found."""
        if self._cached is not None and not force_reload:
            return self._cached

        candidates = []

        env_path = os.environ.get("SELVA_SOUL_PATH")
        if env_path:
            candidates.append(Path(env_path))
        candidates.extend([_PROJECT_SOUL_PATH, _DEFAULT_SOUL_PATH])

        for path in candidates:
            if path.exists() and path.is_file():
                try:
                    text = path.read_text(encoding="utf-8", errors="replace").strip()
                    if len(text) > _MAX_CHARS:
                        logger.warning(
                            "SOUL.md at %s exceeds %d chars — truncating.",
                            path,
                            _MAX_CHARS,
                        )
                        text = text[:_MAX_CHARS] + "\n\n[... truncated ...]"
                    self._cached = text
                    logger.info(
                        "SoulLoader: loaded personality from %s (%d chars).",
                        path,
                        len(text),
                    )
                    return text
                except Exception as exc:
                    logger.warning("SoulLoader: could not read %s: %s", path, exc)

        self._cached = ""
        return ""

    def format_for_prompt(self) -> str:
        """Return the SOUL.md formatted as a system prompt section."""
        content = self.load()
        if not content:
            return ""
        return f"## Agent Personality & Values\n\n{content}\n"


# Module-level singleton
soul_loader = SoulLoader()
