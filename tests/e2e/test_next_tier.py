"""
Tests — Next-Tier: Context Compression, Checkpoints, SOUL.md
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Context Compressor
# ---------------------------------------------------------------------------


class TestContextCompressor:
    def _make_messages(self, n: int) -> list[dict]:
        msgs = [{"role": "system", "content": "You are a helpful assistant."}]
        for i in range(n):
            msgs.append({"role": "user" if i % 2 == 0 else "assistant", "content": f"Message {i}"})
        return msgs

    def test_no_compression_below_threshold(self):
        """Message list below threshold is returned unchanged."""
        from selva_workflows.context_compressor import ContextCompressor

        compressor = ContextCompressor(compress_threshold=20)
        messages = self._make_messages(10)
        result = compressor.compress_sync(messages)
        assert result is messages

    @pytest.mark.asyncio
    async def test_compression_above_threshold(self):
        """Message list above threshold is compressed to head + summary + tail."""
        from selva_workflows.context_compressor import ContextCompressor

        mock_response = MagicMock()
        mock_response.content = "Summary of middle turns."
        mock_router = AsyncMock()
        mock_router.complete = AsyncMock(return_value=mock_response)

        with patch(
            "selva_workflows.context_compressor.get_default_router",
            return_value=mock_router,
            create=True,
        ):
            with patch("selva_workflows.context_compressor.InferenceRequest", create=True):
                with patch("selva_workflows.context_compressor.RoutingPolicy", create=True):
                    with patch("selva_workflows.context_compressor.Sensitivity", create=True):
                        compressor = ContextCompressor(
                            keep_head=2,
                            keep_tail=3,
                            compress_threshold=10,
                        )
                        messages = self._make_messages(15)
                        result = await compressor.compress(messages)

        # head (2) + summary (1) + tail (3) = 6 messages
        assert len(result) == 6
        assert "CONTEXT SUMMARY" in result[2]["content"]

    @pytest.mark.asyncio
    async def test_compression_preserves_system_head(self):
        """System prompt is always in the first position after compression."""
        from selva_workflows.context_compressor import ContextCompressor

        with patch(
            "selva_workflows.context_compressor.get_default_router",
            create=True,
        ) as mock_router_fn:
            mock_router = AsyncMock()
            mock_router.complete = AsyncMock(return_value=MagicMock(content="summary"))
            mock_router_fn.return_value = mock_router
            with patch("selva_workflows.context_compressor.InferenceRequest", create=True):
                with patch("selva_workflows.context_compressor.RoutingPolicy", create=True):
                    with patch("selva_workflows.context_compressor.Sensitivity", create=True):
                        compressor = ContextCompressor(
                            keep_head=2,
                            keep_tail=3,
                            compress_threshold=10,
                        )
                        messages = self._make_messages(15)
                        result = await compressor.compress(messages)
        assert result[0]["role"] == "system"


# ---------------------------------------------------------------------------
# Checkpoint Manager
# ---------------------------------------------------------------------------


class TestCheckpointManager:
    @pytest.mark.asyncio
    async def test_save_and_restore_in_memory(self):
        """Save and restore a state snapshot via in-memory fallback."""
        from nexus_api.checkpoints import CheckpointManager

        mgr = CheckpointManager(db=None)
        state = {"target_url": "https://example.com", "phase_data": {"prd": "Draft"}}
        await mgr.save("run-001", "phase_i", phase_index=1, state=state)
        restored = await mgr.restore("run-001", "phase_i")
        assert restored == state

    @pytest.mark.asyncio
    async def test_restore_nonexistent_returns_none(self):
        """Restoring a non-existent checkpoint returns None."""
        from nexus_api.checkpoints import CheckpointManager

        mgr = CheckpointManager(db=None)
        result = await mgr.restore("nonexistent-run", "phase_i")
        assert result is None


# ---------------------------------------------------------------------------
# SOUL.md Loader
# ---------------------------------------------------------------------------


class TestSoulLoader:
    def test_no_soul_file_returns_empty(self, tmp_path):
        """SoulLoader returns empty string when no SOUL.md is found."""
        from selva_workflows.soul import SoulLoader

        loader = SoulLoader()
        # Override paths to point to temp dir
        with patch("selva_workflows.soul._PROJECT_SOUL_PATH", tmp_path / "nonexistent.md"):
            with patch(
                "selva_workflows.soul._DEFAULT_SOUL_PATH",
                tmp_path / "also_nonexistent.md",
            ):
                result = loader.load(force_reload=True)
        assert result == ""

    def test_loads_soul_from_project_path(self, tmp_path):
        """SoulLoader reads SOUL.md from the project path."""
        soul_path = tmp_path / "SOUL.md"
        soul_path.write_text("# Selva Agent\nYou are professional and precise.")
        from selva_workflows.soul import SoulLoader

        loader = SoulLoader()
        with patch("selva_workflows.soul._PROJECT_SOUL_PATH", soul_path):
            result = loader.load(force_reload=True)
        assert "professional and precise" in result

    def test_oversized_soul_file_truncated(self, tmp_path):
        """SOUL.md files exceeding the token cap are truncated."""
        soul_path = tmp_path / "SOUL.md"
        soul_path.write_text("word " * 50_000)
        from selva_workflows.soul import SoulLoader

        loader = SoulLoader()
        with patch("selva_workflows.soul._PROJECT_SOUL_PATH", soul_path):
            result = loader.load(force_reload=True)
        assert len(result) <= 8_100  # 8000 chars + truncation marker

    def test_format_for_prompt_includes_section_header(self, tmp_path):
        """format_for_prompt wraps content in a section header."""
        soul_path = tmp_path / "SOUL.md"
        soul_path.write_text("You are precise and thoughtful.")
        from selva_workflows.soul import SoulLoader

        loader = SoulLoader()
        with patch("selva_workflows.soul._PROJECT_SOUL_PATH", soul_path):
            result = loader.format_for_prompt()
        assert "Agent Personality" in result
        assert "precise and thoughtful" in result
