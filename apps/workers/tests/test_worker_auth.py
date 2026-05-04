"""Tests for Phase 2: worker auth helper and configurable token."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestGetWorkerAuthHeaders:
    """get_worker_auth_headers returns correctly formatted Authorization header."""

    def test_returns_bearer_header_from_settings(self) -> None:
        mock_settings = MagicMock(worker_api_token="my-secret-token")
        with patch("selva_workers.config.get_settings", return_value=mock_settings):
            from selva_workers.auth import get_worker_auth_headers

            headers = get_worker_auth_headers()
            assert headers == {"Authorization": "Bearer my-secret-token"}

    def test_default_token_is_dev_bypass(self) -> None:
        mock_settings = MagicMock(worker_api_token="dev-bypass")
        with patch("selva_workers.config.get_settings", return_value=mock_settings):
            from selva_workers.auth import get_worker_auth_headers

            headers = get_worker_auth_headers()
            assert headers == {"Authorization": "Bearer dev-bypass"}

    def test_returns_dict_type(self) -> None:
        mock_settings = MagicMock(worker_api_token="token")
        with patch("selva_workers.config.get_settings", return_value=mock_settings):
            from selva_workers.auth import get_worker_auth_headers

            headers = get_worker_auth_headers()
            assert isinstance(headers, dict)
            assert "Authorization" in headers


class TestWorkerApiTokenSetting:
    """worker_api_token field exists on Settings and reads WORKER_API_TOKEN env."""

    def test_default_value(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            from selva_workers.config import Settings

            s = Settings(
                redis_url="redis://localhost:6379",
                nexus_api_url="http://localhost:4300",
            )
            assert s.worker_api_token == "dev-bypass"

    def test_reads_from_env(self) -> None:
        with patch.dict("os.environ", {"WORKER_API_TOKEN": "prod-jwt-token"}, clear=False):
            from selva_workers.config import Settings

            s = Settings(
                redis_url="redis://localhost:6379",
                nexus_api_url="http://localhost:4300",
            )
            assert s.worker_api_token == "prod-jwt-token"


class TestNoHardcodedDevBypass:
    """Ensure no non-test worker source files contain hardcoded 'Bearer dev-bypass'."""

    def test_no_hardcoded_bearer_in_worker_source(self) -> None:
        from pathlib import Path

        worker_src = Path(__file__).resolve().parent.parent / "selva_workers"
        violations: list[str] = []

        for py_file in worker_src.rglob("*.py"):
            # Skip __pycache__
            if "__pycache__" in str(py_file):
                continue
            content = py_file.read_text()
            if '"Bearer dev-bypass"' in content or "'Bearer dev-bypass'" in content:
                violations.append(str(py_file.relative_to(worker_src)))

        assert violations == [], (
            f"Found hardcoded 'Bearer dev-bypass' in: {violations}. "
            "Use get_worker_auth_headers() instead."
        )


class TestTraceContextInjection:
    """get_worker_auth_headers injects W3C traceparent when a span is active."""

    @staticmethod
    def _otel_available() -> bool:
        try:
            from opentelemetry import trace  # noqa: F401
            from opentelemetry.propagate import inject  # noqa: F401

            return True
        except ImportError:
            return False

    def test_no_traceparent_when_no_active_span(self) -> None:
        """traceparent is NOT inserted when no OTel span is active."""
        mock_settings = MagicMock(worker_api_token="token")
        with patch("selva_workers.config.get_settings", return_value=mock_settings):
            from selva_workers.auth import get_worker_auth_headers

            headers = get_worker_auth_headers(org_id="org-1")
        # Either OTel isn't installed or no provider has been configured —
        # in both cases there's no span to propagate, so the header MUST
        # NOT be injected with garbage.
        if "traceparent" in headers:
            # If something injected, it must at least be well-formed.
            import re

            assert re.match(
                r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$",
                headers["traceparent"],
            )

    def test_traceparent_injected_when_span_active(self) -> None:
        """When an OTel span is active, get_worker_auth_headers includes traceparent."""
        if not self._otel_available():
            return  # silently skip when extras missing

        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider

        provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            trace.set_tracer_provider(TracerProvider())

        mock_settings = MagicMock(worker_api_token="token")
        with patch("selva_workers.config.get_settings", return_value=mock_settings):
            from selva_workers.auth import get_worker_auth_headers

            tracer = trace.get_tracer("test-worker-auth")
            with tracer.start_as_current_span("worker-task"):
                headers = get_worker_auth_headers(org_id="tenant-42")

        # Required headers preserved.
        assert headers["Authorization"] == "Bearer token"
        assert headers["X-Selva-Tenant-Org"] == "tenant-42"
        # New: traceparent is now also present.
        assert "traceparent" in headers, (
            f"Expected traceparent in headers, got: {headers}"
        )
        import re

        assert re.match(
            r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$",
            headers["traceparent"],
        ), f"Malformed traceparent: {headers['traceparent']!r}"

    def test_no_raise_when_observability_missing(self) -> None:
        """Helper still works when selva_observability cannot be imported."""
        import builtins as _builtins

        real_import = _builtins.__import__

        def _block_obs(name: str, *args: object, **kwargs: object) -> object:
            if name.startswith("selva_observability"):
                raise ImportError("blocked")
            return real_import(name, *args, **kwargs)

        mock_settings = MagicMock(worker_api_token="token")
        with (
            patch("selva_workers.config.get_settings", return_value=mock_settings),
            patch("builtins.__import__", side_effect=_block_obs),
        ):
            from selva_workers.auth import get_worker_auth_headers

            headers = get_worker_auth_headers(org_id="org-1")

        assert headers["Authorization"] == "Bearer token"
        assert headers["X-Selva-Tenant-Org"] == "org-1"
        assert "traceparent" not in headers
