"""Regression tests for inference-proxy usage normalization.

madfam_inference providers emit ``input_tokens``/``output_tokens`` while the
proxy's ledger writer, event emitter, and OpenAI-compatible response body
speak ``prompt_tokens``/``completion_tokens``. The key mismatch silently
zeroed the RFC 0034 USD usage ledger — every accrual path saw 0 tokens.
"""

from __future__ import annotations

from nexus_api.routers.inference_proxy import _normalize_usage


class TestNormalizeUsage:
    def test_provider_style_keys_are_mapped(self) -> None:
        usage = _normalize_usage({"input_tokens": 120, "output_tokens": 45})
        assert usage == {
            "prompt_tokens": 120,
            "completion_tokens": 45,
            "total_tokens": 165,
        }

    def test_openai_style_keys_pass_through(self) -> None:
        usage = _normalize_usage(
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        )
        assert usage == {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }

    def test_provider_keys_win_when_both_styles_present(self) -> None:
        usage = _normalize_usage(
            {"input_tokens": 7, "output_tokens": 3, "prompt_tokens": 99}
        )
        assert usage["prompt_tokens"] == 7
        assert usage["completion_tokens"] == 3

    def test_total_is_computed_when_absent(self) -> None:
        assert _normalize_usage({"input_tokens": 2, "output_tokens": 8})["total_tokens"] == 10

    def test_none_and_empty_are_safe(self) -> None:
        zero = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        assert _normalize_usage(None) == zero
        assert _normalize_usage({}) == zero
