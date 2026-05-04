"""Tests for post-task learning hooks (PR 2: Agent Learning Loop)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_MOCK_AUTH = {"Authorization": "Bearer test-token"}


def _mock_settings(**overrides):
    """Return a mock settings object for learning tests."""
    defaults = {
        "memory_persist_dir": "/tmp/test-memory",
        "bandit_persist_path": "/tmp/test-bandit.json",
        "nexus_api_url": "http://test:4300",
        "worker_api_token": "dev-bypass",
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


class TestRecordExperience:
    """record_experience stores in ExperienceStore + MemoryManager."""

    @pytest.mark.asyncio
    async def test_completed_task_scores_1_0(self) -> None:
        # ExperienceStore.record and MemoryManager.store_memory are async — must
        # use AsyncMock so `await` succeeds against the mock.
        mock_exp_store = MagicMock()
        mock_exp_store.record = AsyncMock()
        mock_mem_manager = MagicMock()
        mock_mem_manager.store_memory = AsyncMock()

        with (
            patch("selva_workers.config.get_settings", return_value=_mock_settings()),
            patch("selva_memory.ExperienceStore", return_value=mock_exp_store),
            patch("selva_memory.get_embedding_provider", return_value=MagicMock()),
            patch("selva_memory.get_memory_manager", return_value=mock_mem_manager),
        ):
            from selva_workers.learning import record_experience

            await record_experience(
                agent_id="agent-1",
                agent_role="coder",
                task_description="Implement login page",
                graph_type="coding",
                result={"files": ["login.py"]},
                status="completed",
                duration_seconds=45.0,
            )

            mock_exp_store.record.assert_called_once()
            record = mock_exp_store.record.call_args[0][0]
            assert record.score == 1.0
            assert "coding" in record.approach
            assert "status=completed" in record.outcome
            assert "duration=45.0s" in record.outcome

            mock_mem_manager.store_memory.assert_called_once()

    @pytest.mark.asyncio
    async def test_failed_task_scores_0_0(self) -> None:
        mock_exp_store = MagicMock()

        with (
            patch("selva_workers.config.get_settings", return_value=_mock_settings()),
            patch("selva_memory.ExperienceStore", return_value=mock_exp_store),
            patch("selva_memory.get_embedding_provider", return_value=MagicMock()),
            patch("selva_memory.get_memory_manager", return_value=MagicMock()),
        ):
            from selva_workers.learning import record_experience

            await record_experience(
                agent_id="agent-1",
                agent_role="coder",
                task_description="Fix bug",
                graph_type="coding",
                result=None,
                status="failed",
                error_message="IndexError",
            )

            record = mock_exp_store.record.call_args[0][0]
            assert record.score == 0.0
            assert "error=IndexError" in record.outcome

    @pytest.mark.asyncio
    async def test_denied_task_scores_0_2(self) -> None:
        mock_exp_store = MagicMock()

        with (
            patch("selva_workers.config.get_settings", return_value=_mock_settings()),
            patch("selva_memory.ExperienceStore", return_value=mock_exp_store),
            patch("selva_memory.get_embedding_provider", return_value=MagicMock()),
            patch("selva_memory.get_memory_manager", return_value=MagicMock()),
        ):
            from selva_workers.learning import record_experience

            await record_experience(
                agent_id="agent-1",
                agent_role="coder",
                task_description="Refactor auth",
                graph_type="coding",
                result=None,
                status="denied",
                feedback="Needs more tests",
            )

            record = mock_exp_store.record.call_args[0][0]
            assert record.score == 0.2
            assert "feedback=Needs more tests" in record.outcome

    @pytest.mark.asyncio
    async def test_fire_and_forget_on_error(self) -> None:
        """record_experience should not raise even if internals fail."""
        with patch(
            "selva_memory.get_embedding_provider",
            side_effect=RuntimeError("embed fail"),
        ):
            from selva_workers.learning import record_experience

            # Should not raise
            await record_experience(
                agent_id="agent-1",
                agent_role="coder",
                task_description="task",
                graph_type="coding",
                result=None,
                status="failed",
            )


class TestGenerateReflexion:
    """generate_reflexion creates LLM-based or fallback reflections."""

    @pytest.mark.asyncio
    async def test_stores_llm_reflexion(self) -> None:
        mock_exp_store = MagicMock()

        with (
            patch("selva_workers.config.get_settings", return_value=_mock_settings()),
            patch("selva_memory.ExperienceStore", return_value=mock_exp_store),
            patch("selva_memory.get_embedding_provider", return_value=MagicMock()),
            patch(
                "selva_workers.inference.call_llm",
                new_callable=AsyncMock,
                return_value="Lesson 1: Validate inputs. Lesson 2: Add error handling.",
            ),
            patch("selva_workers.inference.get_model_router", return_value=MagicMock()),
        ):
            from selva_workers.learning import generate_reflexion

            await generate_reflexion(
                agent_id="agent-1",
                agent_role="coder",
                task_description="Build API endpoint",
                graph_type="coding",
                error_message="TypeError: missing arg",
            )

            mock_exp_store.record.assert_called_once()
            record = mock_exp_store.record.call_args[0][0]
            assert record.score == 0.3
            assert "reflexion" in record.approach
            assert "Lesson 1" in record.approach
            assert record.metadata.get("type") == "reflection"

    @pytest.mark.asyncio
    async def test_fallback_without_llm(self) -> None:
        mock_exp_store = MagicMock()

        with (
            patch("selva_workers.config.get_settings", return_value=_mock_settings()),
            patch("selva_memory.ExperienceStore", return_value=mock_exp_store),
            patch("selva_memory.get_embedding_provider", return_value=MagicMock()),
            patch(
                "selva_workers.inference.call_llm",
                side_effect=RuntimeError("no LLM"),
            ),
            patch("selva_workers.inference.get_model_router", return_value=MagicMock()),
        ):
            from selva_workers.learning import generate_reflexion

            await generate_reflexion(
                agent_id="agent-1",
                agent_role="coder",
                task_description="Deploy service",
                graph_type="deployment",
                error_message="Connection refused",
            )

            mock_exp_store.record.assert_called_once()
            record = mock_exp_store.record.call_args[0][0]
            assert record.score == 0.3
            assert "Connection refused" in record.approach

    @pytest.mark.asyncio
    async def test_fire_and_forget_on_error(self) -> None:
        with patch(
            "selva_memory.get_embedding_provider",
            side_effect=RuntimeError("fail"),
        ):
            from selva_workers.learning import generate_reflexion

            await generate_reflexion(
                agent_id="agent-1",
                agent_role="coder",
                task_description="task",
                graph_type="coding",
            )


class TestUpdateAgentPerformance:
    """update_agent_performance sends PATCH to nexus-api."""

    @pytest.mark.asyncio
    async def test_patches_completed(self) -> None:
        with (
            patch(
                "selva_workers.http_retry.fire_and_forget_request",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_ffr,
            patch(
                "selva_workers.auth.get_worker_auth_headers",
                return_value=_MOCK_AUTH,
            ),
        ):
            from selva_workers.learning import update_agent_performance

            await update_agent_performance(
                "http://test:4300",
                "agent-1",
                "completed",
                duration_seconds=30.5,
            )

            mock_ffr.assert_called_once()
            body = mock_ffr.call_args.kwargs["json"]
            assert body["tasks_completed_delta"] == 1
            assert body["task_duration_seconds"] == 30.5
            assert body["approval_success_delta"] == 1

    @pytest.mark.asyncio
    async def test_patches_failed(self) -> None:
        with (
            patch(
                "selva_workers.http_retry.fire_and_forget_request",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_ffr,
            patch(
                "selva_workers.auth.get_worker_auth_headers",
                return_value=_MOCK_AUTH,
            ),
        ):
            from selva_workers.learning import update_agent_performance

            await update_agent_performance("http://test:4300", "agent-1", "failed")

            body = mock_ffr.call_args.kwargs["json"]
            assert body["tasks_failed_delta"] == 1
            assert "approval_success_delta" not in body

    @pytest.mark.asyncio
    async def test_skips_unknown_agent(self) -> None:
        with patch(
            "selva_workers.http_retry.fire_and_forget_request",
            new_callable=AsyncMock,
        ) as mock_ffr:
            from selva_workers.learning import update_agent_performance

            await update_agent_performance("http://test:4300", "unknown", "completed")
            mock_ffr.assert_not_called()

    @pytest.mark.asyncio
    async def test_denial_flag(self) -> None:
        with (
            patch(
                "selva_workers.http_retry.fire_and_forget_request",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_ffr,
            patch(
                "selva_workers.auth.get_worker_auth_headers",
                return_value=_MOCK_AUTH,
            ),
        ):
            from selva_workers.learning import update_agent_performance

            await update_agent_performance(
                "http://test:4300",
                "agent-1",
                "completed",
                was_approval_denied=True,
            )

            body = mock_ffr.call_args.kwargs["json"]
            assert body["approval_denial_delta"] == 1
            assert "approval_success_delta" not in body


class TestUpdateBanditReward:
    """update_bandit_reward updates ThompsonBandit."""

    @pytest.mark.asyncio
    async def test_updates_bandit_on_success(self) -> None:
        mock_bandit = MagicMock()

        with (
            patch("selva_workers.config.get_settings", return_value=_mock_settings()),
            patch("selva_orchestrator.bandit.ThompsonBandit", return_value=mock_bandit),
        ):
            from selva_workers.learning import update_bandit_reward

            await update_bandit_reward("agent-1", 1.0)

            mock_bandit.update.assert_called_once_with("agent-1", 1.0)

    @pytest.mark.asyncio
    async def test_skips_unknown_agent(self) -> None:
        with patch(
            "selva_orchestrator.bandit.ThompsonBandit",
        ) as mock_cls:
            from selva_workers.learning import update_bandit_reward

            await update_bandit_reward("unknown", 1.0)
            mock_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_fire_and_forget_on_error(self) -> None:
        with (
            patch("selva_workers.config.get_settings", return_value=_mock_settings()),
            patch(
                "selva_orchestrator.bandit.ThompsonBandit",
                side_effect=RuntimeError("bandit fail"),
            ),
        ):
            from selva_workers.learning import update_bandit_reward

            await update_bandit_reward("agent-1", 0.5)
