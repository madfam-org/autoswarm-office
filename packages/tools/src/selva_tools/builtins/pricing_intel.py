"""Pricing-intelligence tools.

Built for Selva to refine the MADFAM offer catalog over time without
humans having to redo the maths every week. Four tools:

    catalog_load             — read dhanam/catalog.yaml (or a URL) and
                               return the canonical catalog dict.
    catalog_tier_gap_audit   — per product, compute the ratio between
                               consecutive tiers and flag awkward jumps
                               (a 3x price jump on <2x value is a cliff
                               that pushes mid-market customers to
                               self-serve the lower tier forever).
    catalog_promo_stack_check — given the catalog's coupons, compute the
                                effective monthly for every product/tier
                                when the deepest stackable promo fires.
                                Flags cases where effective < cost floor.
    competitor_price_lookup  — pure WebFetch wrapper around a published
                               pricing URL; returns the raw HTML for an
                               LLM-driven parse. Intentionally simple so
                               scrapers don't drift silently on the
                               catalog side.

Design principle: every tool is a **pure analyser**. None of them write
back to the catalog. The agent proposes; a human (or the HITL-confidence
gate, once it hits ``ALLOW_SHADOW``) approves. Never let pricing changes
land without an approval trail — that's the whole reason the catalog
lives in a YAML + sync script rather than a database edit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
import yaml

from ..base import BaseTool, ToolResult
from .http_tools import _build_safe_request_kwargs

DEFAULT_CATALOG_URL = "https://api.dhan.am/v1/billing/catalog"


# -- Shared data shapes -------------------------------------------------------


@dataclass(frozen=True)
class TierPricing:
    """A single tier's price points across currencies + billing cadences."""

    product_slug: str
    product_name: str
    tier_slug: str
    tier_display: str
    dhanam_tier: str  # essentials / pro / premium — Dhanam's canonical tier name
    prices: dict[str, dict[str, int | None]]  # {currency: {monthly:int, yearly:int}}
    features: list[str]

    def monthly(self, currency: str) -> int | None:
        return self.prices.get(currency, {}).get("monthly")

    def yearly(self, currency: str) -> int | None:
        return self.prices.get(currency, {}).get("yearly")

    def yearly_monthly_equivalent(self, currency: str) -> int | None:
        """Monthly cents when paid annually — i.e. yearly_cents / 12."""
        y = self.yearly(currency)
        return y // 12 if y else None


@dataclass
class TierGapFinding:
    product_slug: str
    from_tier: str
    to_tier: str
    currency: str
    from_monthly: int
    to_monthly: int
    ratio: float
    feature_delta: int
    severity: str  # ok | review | cannibalization_risk
    note: str


@dataclass
class PromoStackFinding:
    product_slug: str
    tier_slug: str
    coupon: str
    currency: str
    list_monthly: int
    effective_monthly: int
    total_discount_pct: float
    severity: str  # ok | review | margin_risk
    note: str


@dataclass
class CatalogAudit:
    product_count: int
    tier_count: int
    coupon_count: int
    tier_gaps: list[TierGapFinding] = field(default_factory=list)
    promo_stacks: list[PromoStackFinding] = field(default_factory=list)
    missing_currency_parity: list[str] = field(default_factory=list)
    unmonetized_products: list[str] = field(default_factory=list)


# -- Internal: catalog normalisation ------------------------------------------


def _flatten_tiers(catalog: dict[str, Any]) -> list[TierPricing]:
    out: list[TierPricing] = []
    for slug, product in (catalog.get("products") or {}).items():
        name = product.get("name") or slug
        for tier_slug, tier in (product.get("tiers") or {}).items():
            out.append(
                TierPricing(
                    product_slug=slug,
                    product_name=name,
                    tier_slug=tier_slug,
                    tier_display=tier.get("display_name") or tier_slug,
                    dhanam_tier=tier.get("dhanam_tier") or "",
                    prices=tier.get("prices") or {},
                    features=tier.get("features") or [],
                )
            )
    return out


def _load_catalog_from_url(url: str) -> dict[str, Any]:
    """Fetch the Dhanam billing-catalog API and shape it like catalog.yaml.

    The Dhanam API returns DB-materialised rows with snake_case slugs. We
    remap to the YAML shape so the downstream analysers work against a
    single format regardless of source.
    """
    request_kwargs, _ = _build_safe_request_kwargs(
        "GET",
        url,
        headers={"User-Agent": "Selva pricing-intel bot"},
        extra={"timeout": 10.0, "follow_redirects": True},
    )
    with httpx.Client(
        trust_env=False,
        transport=httpx.HTTPTransport(retries=0),
    ) as client:
        resp = client.request(**request_kwargs)
    resp.raise_for_status()
    data = resp.json()

    products: dict[str, Any] = {}
    for p in data.get("products") or []:
        tiers: dict[str, Any] = {}
        for t in p.get("tiers") or []:
            tiers[t.get("tierSlug") or t.get("tier_slug") or ""] = {
                "dhanam_tier": t.get("dhanamTier") or t.get("dhanam_tier"),
                "display_name": t.get("displayName") or t.get("display_name"),
                "prices": t.get("prices") or {},
                "features": t.get("features") or [],
                "metadata": t.get("metadata") or {},
            }
        products[p.get("slug")] = {
            "name": p.get("name"),
            "description": p.get("description"),
            "category": p.get("category"),
            "website": p.get("websiteUrl") or p.get("website"),
            "tiers": tiers,
            "credit_costs": {
                c.get("operation"): c.get("credits") for c in (p.get("creditCosts") or [])
            },
        }
    return {"products": products, "coupons": data.get("coupons") or {}}


def _load_catalog_from_yaml(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# -- Tool 1: catalog_load -----------------------------------------------------


class CatalogLoadTool(BaseTool):
    name = "catalog_load"
    description = (
        "Load the MADFAM product catalog from either a local dhanam/catalog.yaml "
        "path or the public Dhanam billing-catalog API. Returns a summary "
        "(products, tiers, coupons) the LLM can iterate over. Prefer the URL "
        "form in production so the catalog is always live."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": (
                        "Either an absolute filesystem path to a catalog.yaml "
                        "OR an https URL to a Dhanam /v1/billing/catalog "
                        f"endpoint. Defaults to {DEFAULT_CATALOG_URL}."
                    ),
                },
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        source: str = kwargs.get("source") or DEFAULT_CATALOG_URL
        try:
            if source.startswith(("http://", "https://")):
                catalog = _load_catalog_from_url(source)
            else:
                catalog = _load_catalog_from_yaml(source)
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"failed to load catalog from {source}: {type(exc).__name__}: {exc}",
            )

        products = list((catalog.get("products") or {}).keys())
        coupons = list((catalog.get("coupons") or {}).keys())
        tier_count = sum(
            len(p.get("tiers") or {}) for p in (catalog.get("products") or {}).values()
        )
        return ToolResult(
            success=True,
            output=(
                f"Loaded catalog: {len(products)} products, {tier_count} tiers, "
                f"{len(coupons)} coupons."
            ),
            data={
                "source": source,
                "products": products,
                "tier_count": tier_count,
                "coupons": coupons,
                "catalog": catalog,
            },
        )


# -- Tool 2: catalog_tier_gap_audit -------------------------------------------


def audit_tier_gaps(catalog: dict[str, Any], *, currency: str = "MXN") -> list[TierGapFinding]:
    """For each product, score the jump between consecutive tiers.

    Heuristics (tuned for SaaS ladders):
        ratio < 1.8     → `review` (upper tier too close; no reason to upgrade)
        ratio >= 2.0 AND feature_delta <= 2
                       → `cannibalization_risk` (big jump, little added value)
        ratio > 4.0    → `review` (too steep; prospects drop off)
        otherwise      → `ok`
    """
    findings: list[TierGapFinding] = []
    for tiers in _group_by_product(catalog):
        # Only consider tiers with a list monthly price in the target currency.
        priced = [t for t in tiers if t.monthly(currency)]
        priced.sort(key=lambda t: t.monthly(currency) or 0)
        for a, b in zip(priced, priced[1:], strict=False):
            a_m, b_m = a.monthly(currency) or 0, b.monthly(currency) or 0
            if not a_m:
                continue
            ratio = b_m / a_m
            feat_delta = len(b.features) - len(a.features)
            severity, note = _classify_tier_gap(ratio, feat_delta)
            findings.append(
                TierGapFinding(
                    product_slug=a.product_slug,
                    from_tier=a.tier_slug,
                    to_tier=b.tier_slug,
                    currency=currency,
                    from_monthly=a_m,
                    to_monthly=b_m,
                    ratio=round(ratio, 2),
                    feature_delta=feat_delta,
                    severity=severity,
                    note=note,
                )
            )
    return findings


def _classify_tier_gap(ratio: float, feat_delta: int) -> tuple[str, str]:
    if ratio < 1.8:
        return (
            "review",
            f"upper tier is only {ratio:.2f}x the lower — weak upgrade incentive",
        )
    if ratio >= 2.0 and feat_delta <= 2:
        return (
            "cannibalization_risk",
            f"{ratio:.2f}x price jump for only +{feat_delta} features — "
            "mid-market will stay on the lower tier forever",
        )
    if ratio > 4.0:
        return (
            "review",
            f"{ratio:.2f}x jump is steep — missing middle tier loses prospects",
        )
    return ("ok", f"{ratio:.2f}x ratio, +{feat_delta} features — healthy ladder")


def _group_by_product(catalog: dict[str, Any]) -> list[list[TierPricing]]:
    by_slug: dict[str, list[TierPricing]] = {}
    for t in _flatten_tiers(catalog):
        by_slug.setdefault(t.product_slug, []).append(t)
    return list(by_slug.values())


class CatalogTierGapTool(BaseTool):
    name = "catalog_tier_gap_audit"
    description = (
        "Audit tier-to-tier price jumps in the MADFAM catalog. Flags "
        "cannibalization risks (big price jump, small feature delta), "
        "missing middle tiers, and upgrade-incentive gaps. Returns a list "
        "of findings per product."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "currency": {
                    "type": "string",
                    "description": "Currency code to audit (MXN or USD). Default MXN.",
                },
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        source: str = kwargs.get("source") or DEFAULT_CATALOG_URL
        currency: str = (kwargs.get("currency") or "MXN").upper()
        try:
            if source.startswith(("http://", "https://")):
                catalog = _load_catalog_from_url(source)
            else:
                catalog = _load_catalog_from_yaml(source)
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"failed to load catalog: {exc}",
            )

        findings = audit_tier_gaps(catalog, currency=currency)
        risks = [f for f in findings if f.severity == "cannibalization_risk"]
        reviews = [f for f in findings if f.severity == "review"]
        summary = (
            f"{len(findings)} tier transitions audited · "
            f"{len(risks)} cannibalization risk · {len(reviews)} need review"
        )
        return ToolResult(
            success=True,
            output=summary,
            data={
                "currency": currency,
                "total_transitions": len(findings),
                "cannibalization_risks": len(risks),
                "reviews": len(reviews),
                "findings": [f.__dict__ for f in findings],
            },
        )


# -- Tool 3: catalog_promo_stack_check ----------------------------------------


def apply_coupon(amount: int, coupon: dict[str, Any], currency: str) -> int:
    """Return the post-coupon cents given the coupon spec from catalog.yaml."""
    if "percent_off" in coupon:
        pct = float(coupon["percent_off"])
        return int(round(amount * (1 - pct / 100.0)))
    if "amount_off_cents" in coupon:
        coupon_currency = (coupon.get("currency") or "").upper()
        if coupon_currency and coupon_currency != currency.lower() and coupon_currency != currency:
            # Coupon is denominated in a different currency — skip.
            return amount
        return max(0, amount - int(coupon["amount_off_cents"]))
    return amount


def audit_promo_stacks(
    catalog: dict[str, Any], *, currency: str = "MXN"
) -> list[PromoStackFinding]:
    """For every (product, tier), find the deepest applicable coupon.

    Stripe only applies ONE coupon per subscription at a time, so "stacking"
    in practice means picking the best single coupon + yearly discount.
    When that combined discount produces a cost floor risk, flag it.
    """
    coupons = catalog.get("coupons") or {}
    findings: list[PromoStackFinding] = []
    for tier in _flatten_tiers(catalog):
        list_monthly = tier.monthly(currency)
        if not list_monthly:
            continue
        # For each coupon applicable to this product, compute effective.
        applicable = [
            (name, spec)
            for name, spec in coupons.items()
            if tier.product_slug in (spec.get("products") or [])
        ]
        if not applicable:
            findings.append(
                PromoStackFinding(
                    product_slug=tier.product_slug,
                    tier_slug=tier.tier_slug,
                    coupon="(none)",
                    currency=currency,
                    list_monthly=list_monthly,
                    effective_monthly=list_monthly,
                    total_discount_pct=0.0,
                    severity="ok",
                    note="no promo applies — list price only",
                )
            )
            continue
        # Deepest discount wins (Stripe applies one per sub).
        deepest = min(
            applicable,
            key=lambda kv: apply_coupon(list_monthly, kv[1], currency),
        )
        name, spec = deepest
        effective = apply_coupon(list_monthly, spec, currency)
        pct = (1 - effective / list_monthly) * 100 if list_monthly else 0
        # Layer in yearly discount if the tier has yearly pricing.
        yearly_equiv = tier.yearly_monthly_equivalent(currency)
        if yearly_equiv and yearly_equiv < effective:
            effective = apply_coupon(yearly_equiv, spec, currency)
            pct = (1 - effective / list_monthly) * 100
        severity, note = _classify_promo_stack(pct, effective)
        findings.append(
            PromoStackFinding(
                product_slug=tier.product_slug,
                tier_slug=tier.tier_slug,
                coupon=name,
                currency=currency,
                list_monthly=list_monthly,
                effective_monthly=effective,
                total_discount_pct=round(pct, 1),
                severity=severity,
                note=note,
            )
        )
    return findings


def _classify_promo_stack(pct: float, effective_cents: int) -> tuple[str, str]:
    if pct >= 60 and effective_cents < 5000:
        return (
            "margin_risk",
            f"{pct:.1f}% off + effective under 50 currency units — review margin floor",
        )
    if pct >= 55:
        return (
            "review",
            f"{pct:.1f}% off is aggressive — confirm gross margin survives",
        )
    if pct >= 45:
        return ("ok", f"{pct:.1f}% off — healthy intro discount")
    return ("ok", f"{pct:.1f}% off — conservative")


class CatalogPromoStackTool(BaseTool):
    name = "catalog_promo_stack_check"
    description = (
        "For every (product, tier) in the catalog, compute the effective "
        "monthly price when the deepest applicable coupon fires (with "
        "yearly-discount layered). Flags cases where the stacked discount "
        "crosses a margin-risk threshold."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "currency": {"type": "string"},
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        source: str = kwargs.get("source") or DEFAULT_CATALOG_URL
        currency: str = (kwargs.get("currency") or "MXN").upper()
        try:
            if source.startswith(("http://", "https://")):
                catalog = _load_catalog_from_url(source)
            else:
                catalog = _load_catalog_from_yaml(source)
        except Exception as exc:
            return ToolResult(success=False, error=f"failed to load catalog: {exc}")

        findings = audit_promo_stacks(catalog, currency=currency)
        risks = [f for f in findings if f.severity == "margin_risk"]
        reviews = [f for f in findings if f.severity == "review"]
        summary = (
            f"{len(findings)} tier/promo combos audited · "
            f"{len(risks)} margin risk · {len(reviews)} need review"
        )
        return ToolResult(
            success=True,
            output=summary,
            data={
                "currency": currency,
                "margin_risks": len(risks),
                "reviews": len(reviews),
                "findings": [f.__dict__ for f in findings],
            },
        )


# -- Tool 4: competitor_price_lookup ------------------------------------------


class CompetitorPriceLookupTool(BaseTool):
    name = "competitor_price_lookup"
    description = (
        "Fetch a competitor's public pricing page and return the raw HTML "
        "for an LLM-driven parse. Intentionally dumb: no regex, no HTML "
        "normalisation — so a page redesign surfaces as a parse failure "
        "the agent has to acknowledge, not a silently stale datum."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full https URL of the pricing page.",
                },
                "user_agent": {
                    "type": "string",
                    "description": (
                        "Optional User-Agent override. Default is a polite "
                        "Selva/pricing-intel identifier so sites can block/"
                        "rate-limit us deliberately if they choose."
                    ),
                },
            },
            "required": ["url"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        url: str = kwargs.get("url") or ""
        if not url.startswith(("http://", "https://")):
            return ToolResult(success=False, error="url must start with http(s)://")
        ua = kwargs.get("user_agent") or "Selva pricing-intel bot (contact: ops@madfam.io)"
        try:
            # Keep competitor lookups safe from SSRF/rebinding by using the
            # shared request builder used across platform tools.
            request_kwargs, original_url = _build_safe_request_kwargs(
                "GET",
                url,
                headers={"User-Agent": ua},
                extra={"timeout": 15.0, "follow_redirects": True},
            )
            async with httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                headers={"User-Agent": ua},
                trust_env=False,
            ) as http:
                resp = await http.request(**request_kwargs)
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"fetch failed: {type(exc).__name__}: {exc}",
            )
        if resp.status_code >= 400:
            return ToolResult(
                success=False,
                error=f"non-2xx: {resp.status_code}",
                data={"status_code": resp.status_code, "body_snippet": resp.text[:500]},
            )
        # Cap body size so we don't drown the LLM in marketing fluff.
        body = resp.text[:50_000]
        return ToolResult(
            success=True,
            output=f"fetched {len(body)} chars from {original_url} (HTTP {resp.status_code})",
            data={
                "url": original_url,
                "status_code": resp.status_code,
                "body": body,
                "truncated": len(resp.text) > 50_000,
            },
        )
