"""SPF / DKIM / DMARC alignment preflight for ``agent_identified`` sends.

The ``agent_identified`` voice mode sends from ``<slug>@selva.town``.
For those to land reliably the customer's ``selva.town`` domain must
be aligned — we don't want to find out about misconfiguration by
watching messages bounce into spam.

The check is advisory: the tool calls it *before* handing off to Resend
and refuses the send when the domain fails. Results are cached for
``_TTL_SECONDS`` to keep the check off the send-path's hot loop.

This module uses ``dnspython`` when available; if the library is not
installed (dev environments) the check returns a permissive result
with ``unknown`` status so development is not blocked.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger("selva.email.spf")

_TTL_SECONDS = 600  # 10 minutes
_CACHE: dict[str, tuple[float, SpfResult]] = {}


@dataclass(frozen=True)
class SpfResult:
    """Outcome of the DNS preflight."""

    domain: str
    spf_ok: bool
    dkim_ok: bool
    dmarc_ok: bool
    status: str  # "pass" | "fail" | "unknown"
    reason: str

    @property
    def aligned(self) -> bool:
        return self.spf_ok and self.dkim_ok and self.dmarc_ok


def _cached(domain: str) -> SpfResult | None:
    entry = _CACHE.get(domain)
    if entry is None:
        return None
    expires_at, result = entry
    if expires_at < time.time():
        _CACHE.pop(domain, None)
        return None
    return result


def _store(domain: str, result: SpfResult) -> None:
    _CACHE[domain] = (time.time() + _TTL_SECONDS, result)


def check_alignment(domain: str = "selva.town") -> SpfResult:
    """Return the SPF/DKIM/DMARC alignment for ``domain``.

    Results are cached for 10 minutes to keep repeated sends cheap.
    """
    cached = _cached(domain)
    if cached is not None:
        return cached

    try:
        import dns.resolver
    except ImportError:
        result = SpfResult(
            domain=domain,
            spf_ok=False,
            dkim_ok=False,
            dmarc_ok=False,
            status="unknown",
            reason="dnspython not installed",
        )
        _store(domain, result)
        return result

    def _txt(name: str) -> list[str]:
        try:
            answers = dns.resolver.resolve(name, "TXT", lifetime=5.0)
            return [b"".join(a.strings).decode("utf-8", errors="ignore") for a in answers]
        except Exception:
            return []

    spf_records = _txt(domain)
    spf_ok = any(r.startswith("v=spf1") and "include:" in r for r in spf_records)

    dkim_records = _txt(f"resend._domainkey.{domain}")
    dkim_ok = any("v=DKIM1" in r for r in dkim_records)

    dmarc_records = _txt(f"_dmarc.{domain}")
    dmarc_ok = any(r.startswith("v=DMARC1") for r in dmarc_records)

    if spf_ok and dkim_ok and dmarc_ok:
        status, reason = "pass", "SPF/DKIM/DMARC aligned"
    else:
        status = "fail"
        missing = [
            label
            for label, ok in (("SPF", spf_ok), ("DKIM", dkim_ok), ("DMARC", dmarc_ok))
            if not ok
        ]
        reason = f"Missing/invalid: {', '.join(missing)}"

    result = SpfResult(
        domain=domain,
        spf_ok=spf_ok,
        dkim_ok=dkim_ok,
        dmarc_ok=dmarc_ok,
        status=status,
        reason=reason,
    )
    _store(domain, result)
    if status == "fail":
        logger.warning("SPF alignment check failed for %s: %s", domain, reason)
    return result
