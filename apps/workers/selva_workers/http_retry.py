"""Shared fire-and-forget HTTP request utility with retry and circuit breaker."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# -- Module-internal constants -------------------------------------------------
# Circuit breaker tuning. These match the docstrings in CLAUDE.md
# ("5 failures → 30s cooldown"). Module-level rather than ops-tunable
# Settings because the values are tightly coupled to the worker's HTTP
# retry budget (3 attempts × 0.5s backoff base) — changing them in
# isolation tends to mask bugs rather than fix them.
_CB_THRESHOLD: int = 5
_CB_WINDOW_S: float = 30.0
_CB_COOLDOWN_S: float = 30.0

# Module-level circuit breaker state, keyed by URL prefix (scheme://host:port).
# Thread-safety: Workers run in a single-threaded asyncio event loop.  Dict
# get/set operations are GIL-atomic under CPython, and the check-then-act
# pattern in _get_circuit_breaker() is safe because all callers are async
# coroutines executing on the same thread.
_circuit_state: dict[str, _CircuitBreaker] = {}


class _CircuitBreaker:
    """Simple circuit breaker: opens after N failures in a window, cools down for a period."""

    __slots__ = ("_failures", "_open_until", "_threshold", "_window", "_cooldown")

    def __init__(
        self,
        threshold: int = _CB_THRESHOLD,
        window: float = _CB_WINDOW_S,
        cooldown: float = _CB_COOLDOWN_S,
    ) -> None:
        self._failures: deque[float] = deque()
        self._open_until: float = 0.0
        self._threshold = threshold
        self._window = window
        self._cooldown = cooldown

    def is_open(self) -> bool:
        now = time.monotonic()
        if now < self._open_until:
            return True
        # Purge old failures outside the window.
        while self._failures and (now - self._failures[0]) > self._window:
            self._failures.popleft()
        return False

    def record_failure(self) -> None:
        now = time.monotonic()
        self._failures.append(now)
        # Purge old failures.
        while self._failures and (now - self._failures[0]) > self._window:
            self._failures.popleft()
        if len(self._failures) >= self._threshold:
            self._open_until = now + self._cooldown
            logger.warning(
                "Circuit breaker opened for %.0fs after %d failures",
                self._cooldown,
                self._threshold,
            )

    def record_success(self) -> None:
        self._failures.clear()
        self._open_until = 0.0


def _get_circuit_breaker(url: str) -> _CircuitBreaker:
    """Get or create a circuit breaker keyed by URL prefix (scheme://host:port)."""
    parsed = urlparse(url)
    prefix = f"{parsed.scheme}://{parsed.netloc}"
    if prefix not in _circuit_state:
        _circuit_state[prefix] = _CircuitBreaker()
    return _circuit_state[prefix]


async def fire_and_forget_request(
    method: str,
    url: str,
    *,
    json: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 5.0,
    max_retries: int = 3,
    base_delay: float = 0.5,
) -> bool:
    """Make an HTTP request with retries and circuit breaker.

    Exponential backoff: ``base_delay * 2^attempt`` (0.5s -> 1s -> 2s).
    Never raises; returns ``True`` on success, ``False`` on failure.
    """
    cb = _get_circuit_breaker(url)
    if cb.is_open():
        logger.debug("Circuit breaker open, skipping request to %s", url)
        return False

    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.request(method, url, json=json, headers=headers)
                if resp.status_code < 500:
                    cb.record_success()
                    if resp.status_code not in (200, 201, 204):
                        logger.warning(
                            "Request to %s returned %d: %s",
                            url,
                            resp.status_code,
                            resp.text[:200],
                        )
                    return resp.status_code < 400
                # 5xx -> retry
                logger.warning(
                    "Request to %s returned %d (attempt %d/%d)",
                    url,
                    resp.status_code,
                    attempt + 1,
                    max_retries,
                )
        except Exception:
            logger.warning(
                "Request to %s failed (attempt %d/%d)",
                url,
                attempt + 1,
                max_retries,
                exc_info=True,
            )

        cb.record_failure()
        if attempt < max_retries - 1:
            delay = base_delay * (2**attempt)
            await asyncio.sleep(delay)

    return False
