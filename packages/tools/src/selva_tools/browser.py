"""
Gap 1: Browser & Vision Tooling

Wraps Playwright async API into callable tool functions, giving Selva
the same browser automation and vision capabilities as Hermes Agent.

Falls back to requests if Playwright is not installed, so the package
remains importable in environments without a browser.
"""

from __future__ import annotations

import base64
import logging

logger = logging.getLogger(__name__)

PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.async_api import async_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    logger.warning("playwright not installed — browser tools will fall back to requests.")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def browser_navigate(url: str, timeout_ms: int = 30_000) -> dict:
    """
    Navigate headless Chromium to *url* and return status + final URL.

    Returns:
        {"status": 200, "url": "<final_url>"}
    """
    if not PLAYWRIGHT_AVAILABLE:
        return _requests_fallback_nav(url)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        response = await page.goto(url, timeout=timeout_ms, wait_until="networkidle")
        result = {"status": response.status if response else 0, "url": page.url}
        await browser.close()
    return result


async def browser_extract(
    url: str,
    selector: str | None = None,
    timeout_ms: int = 30_000,
) -> str:
    """
    Navigate to *url* and return inner text of *selector* (or full body).

    Falls back to requests.get for non-JS pages when Playwright is absent.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return _requests_fallback_extract(url)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, timeout=timeout_ms, wait_until="networkidle")

        if selector:
            elements = await page.query_selector_all(selector)
            texts = [await el.inner_text() for el in elements]
            content = "\n".join(texts)
        else:
            content = await page.inner_text("body")

        await browser.close()
    return content


async def browser_screenshot(url: str, timeout_ms: int = 30_000) -> str:
    """
    Navigate to *url*, take a full-page screenshot, return base64-encoded PNG.

    Returns an empty string if Playwright is unavailable.
    """
    if not PLAYWRIGHT_AVAILABLE:
        logger.warning("browser_screenshot: Playwright unavailable — returning empty string.")
        return ""

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, timeout=timeout_ms, wait_until="networkidle")
        png_bytes = await page.screenshot(full_page=True)
        await browser.close()

    return base64.b64encode(png_bytes).decode()


async def browser_click(url: str, selector: str, timeout_ms: int = 30_000) -> dict:
    """Click an element matching *selector* on *url*."""
    if not PLAYWRIGHT_AVAILABLE:
        return {"error": "Playwright unavailable"}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, timeout=timeout_ms, wait_until="networkidle")
        await page.click(selector, timeout=timeout_ms)
        result = {"clicked": selector, "url": page.url}
        await browser.close()
    return result


async def browser_fill(url: str, selector: str, value: str, timeout_ms: int = 30_000) -> dict:
    """Fill an input field matching *selector* on *url* with *value*."""
    if not PLAYWRIGHT_AVAILABLE:
        return {"error": "Playwright unavailable"}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, timeout=timeout_ms, wait_until="networkidle")
        await page.fill(selector, value, timeout=timeout_ms)
        result = {"filled": selector, "value": value}
        await browser.close()
    return result


async def browser_evaluate(url: str, js: str, timeout_ms: int = 30_000):
    """Evaluate *js* in the browser context of *url* and return the result."""
    if not PLAYWRIGHT_AVAILABLE:
        return {"error": "Playwright unavailable"}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, timeout=timeout_ms, wait_until="networkidle")
        result = await page.evaluate(js)
        await browser.close()
    return result


async def vision_describe(image_b64: str, prompt: str = "Describe this image in detail.") -> str:
    """
    Send *image_b64* (base64 PNG) to the active LLM's vision endpoint.

    Requires the configured provider to support vision (e.g., Claude 3, GPT-4o).
    Falls back to a placeholder description if no vision provider is available.
    """
    try:
        from madfam_inference import get_default_router  # type: ignore
        from madfam_inference.types import InferenceRequest, RoutingPolicy, Sensitivity

        request = InferenceRequest(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            system_prompt="You are a vision AI. Describe images accurately and concisely.",
            policy=RoutingPolicy(
                sensitivity=Sensitivity.INTERNAL,
                task_type="vision",
                temperature=0.2,
                max_tokens=512,
            ),
        )
        router = get_default_router()
        response = await router.complete(request)
        return response.content
    except Exception as exc:
        logger.warning("vision_describe: LLM unavailable (%s) — returning placeholder.", exc)
        return "[Vision description unavailable — no vision-capable provider configured]"


# ---------------------------------------------------------------------------
# Fallbacks
# ---------------------------------------------------------------------------


def _requests_fallback_nav(url: str) -> dict:
    try:
        import httpx

        from selva_tools.builtins.http_tools import _build_safe_request_kwargs

        request_kwargs, resolved_url = _build_safe_request_kwargs(
            "HEAD",
            url,
            headers={"User-Agent": "Selva-Browser/1.0"},
            extra={"timeout": 10.0, "follow_redirects": True},
        )
        with httpx.Client(
            trust_env=False,
            transport=httpx.HTTPTransport(retries=0),
        ) as client:
            response = client.request(**request_kwargs)
        return {"status": response.status_code, "url": resolved_url}
    except Exception as exc:
        return {"status": 0, "url": url, "error": str(exc)}


def _requests_fallback_extract(url: str) -> str:
    try:
        from html.parser import HTMLParser

        import httpx

        from selva_tools.builtins.http_tools import _build_safe_request_kwargs

        class _TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self._parts: list[str] = []

            def handle_data(self, data):
                self._parts.append(data)

            @property
            def text(self):
                return " ".join(self._parts)

        request_kwargs, _ = _build_safe_request_kwargs(
            "GET",
            url,
            headers={"User-Agent": "Selva-Browser/1.0"},
            extra={"timeout": 15.0, "follow_redirects": True},
        )
        with httpx.Client(
            trust_env=False,
            transport=httpx.HTTPTransport(retries=0),
        ) as client:
            r = client.request(**request_kwargs)
        r.raise_for_status()
        p = _TextExtractor()
        p.feed(r.text)
        return p.text
    except Exception as exc:
        logger.error("requests fallback failed for %s: %s", url, exc)
        return ""
