"""
Gap 7: Prompt Caching — Anthropic Prefix Caching

Applies Anthropic cache_control breakpoints at the last immutable boundary
in the system prompt (after personality/skills/memory, before user turn),
enabling prompt prefix caching that cuts inference costs on repeated calls.

Non-Anthropic providers are completely untouched.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Minimum token threshold before caching is worth the overhead
_MIN_CACHE_TOKENS = 1024


# Approximate token count — 1 token ≈ 4 chars (conservative estimate)
def _approx_tokens(text: str) -> int:
    return len(text) // 4


class PromptCacheManager:
    """
    Manages Anthropic prompt prefix caching for madfam_inference requests.

    Usage:
        mgr = PromptCacheManager()
        messages = mgr.apply_cache_breakpoints(messages, provider="anthropic")
    """

    def should_cache(self, system_prompt: str, provider: str) -> bool:
        """Return True if caching is appropriate for this provider and prompt."""
        if provider.lower() not in ("anthropic", "claude"):
            return False
        return _approx_tokens(system_prompt) >= _MIN_CACHE_TOKENS

    def apply_cache_breakpoints(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        provider: str,
    ) -> tuple[list[dict[str, Any]], str | list[dict[str, Any]]]:
        """
        Inject Anthropic ``cache_control`` breakpoints.

        The system prompt is converted to a structured content block with
        a cache_control marker at the end of the immutable prefix region
        (i.e., after skills/memory/personality, before the first user turn).

        Args:
            messages: Existing message list.
            system_prompt: Raw system prompt string.
            provider: Provider name (e.g., "anthropic").

        Returns:
            (messages, system_with_cache) — messages unchanged for non-Anthropic;
            system prompt converted to a cache-annotated content block.
        """
        if not self.should_cache(system_prompt, provider):
            return messages, system_prompt

        # Anthropic accepts system as either a string or a list of content blocks.
        # Inject cache_control at the end of the system block.
        system_with_cache = [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        logger.debug(
            "PromptCacheManager: injecting cache breakpoint on ~%d-token system prompt.",
            _approx_tokens(system_prompt),
        )
        return messages, system_with_cache

    def extract_cache_metrics(self, response_headers: dict) -> dict:
        """
        Extract cache hit/miss tokens from Anthropic API response headers.

        Returns:
            {"cache_read_tokens": int, "cache_write_tokens": int}
        """
        return {
            "cache_read_tokens": int(response_headers.get("anthropic-cache-read-input-tokens", 0)),
            "cache_write_tokens": int(
                response_headers.get("anthropic-cache-creation-input-tokens", 0)
            ),
        }
