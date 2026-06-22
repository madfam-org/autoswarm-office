"""Unit tests for the pricing_intel tools.

Covers the pure catalog-analysis functions (tier-gap classification,
promo-stack evaluation, bucketing helpers) and the Tool interfaces.
No network calls: `competitor_price_lookup` is exercised via
`httpx.MockTransport`. Catalog loading uses inline YAML strings so
we never depend on a live dhanam/catalog.yaml snapshot.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from selva_tools.builtins.pricing_intel import (
    CatalogLoadTool,
    CatalogPromoStackTool,
    CatalogTierGapTool,
    CompetitorPriceLookupTool,
    PromoStackFinding,
    TierGapFinding,
    _classify_promo_stack,
    _classify_tier_gap,
    _load_catalog_from_yaml,
    apply_coupon,
    audit_promo_stacks,
    audit_tier_gaps,
)


def _bypass_safe_request_kwargs(method: str, url: str, **kwargs: Any) -> tuple[dict[str, Any], str]:
    """Test helper: skip DNS pinning so MockTransport can intercept httpx."""
    extra = kwargs.get("extra") or {}
    request_kwargs: dict[str, Any] = {
        "method": method,
        "url": url,
        "headers": kwargs.get("headers") or {},
    }
    if "timeout" in extra:
        request_kwargs["timeout"] = extra["timeout"]
    if extra.get("follow_redirects"):
        request_kwargs["follow_redirects"] = True
    return request_kwargs, url

# ============================================================================
# apply_coupon — percent vs amount-off, currency guards
# ============================================================================


class TestApplyCoupon:
    def test_percent_off(self) -> None:
        assert apply_coupon(10000, {"percent_off": 40}, "MXN") == 6000

    def test_percent_off_half(self) -> None:
        assert apply_coupon(10000, {"percent_off": 50}, "MXN") == 5000

    def test_amount_off_same_currency(self) -> None:
        assert apply_coupon(10000, {"amount_off_cents": 400, "currency": "mxn"}, "MXN") == 9600

    def test_amount_off_wrong_currency_skipped(self) -> None:
        # Coupon is in USD, the tier is in MXN — coupon should not apply.
        assert apply_coupon(10000, {"amount_off_cents": 400, "currency": "usd"}, "MXN") == 10000

    def test_amount_off_never_goes_below_zero(self) -> None:
        assert apply_coupon(100, {"amount_off_cents": 500, "currency": "mxn"}, "MXN") == 0

    def test_unknown_coupon_shape_noop(self) -> None:
        assert apply_coupon(10000, {"duration": "forever"}, "MXN") == 10000


# ============================================================================
# Tier-gap classification
# ============================================================================


class TestClassifyTierGap:
    def test_weak_upgrade_incentive(self) -> None:
        sev, note = _classify_tier_gap(ratio=1.5, feat_delta=3)
        assert sev == "review"
        assert "weak" in note.lower()

    def test_cannibalization_risk_big_jump_small_delta(self) -> None:
        sev, note = _classify_tier_gap(ratio=3.0, feat_delta=1)
        assert sev == "cannibalization_risk"
        assert "mid-market" in note.lower()

    def test_too_steep_ratio_is_review(self) -> None:
        sev, _note = _classify_tier_gap(ratio=5.0, feat_delta=10)
        assert sev == "review"

    def test_healthy_ladder(self) -> None:
        sev, _note = _classify_tier_gap(ratio=2.5, feat_delta=5)
        assert sev == "ok"


class TestClassifyPromoStack:
    def test_deep_discount_flags_margin_risk(self) -> None:
        sev, _ = _classify_promo_stack(pct=70.0, effective_cents=3000)
        assert sev == "margin_risk"

    def test_aggressive_discount_review(self) -> None:
        sev, _ = _classify_promo_stack(pct=58.0, effective_cents=100_000)
        assert sev == "review"

    def test_healthy_discount_ok(self) -> None:
        sev, _ = _classify_promo_stack(pct=20.0, effective_cents=80000)
        assert sev == "ok"


# ============================================================================
# audit_tier_gaps + audit_promo_stacks
# ============================================================================


_SAMPLE_CATALOG = """
products:
  acme:
    name: Acme
    tiers:
      entry:
        dhanam_tier: essentials
        prices: { MXN: { monthly: 10000 } }
        features:
          - "f1"
          - "f2"
          - "f3"
      pro:
        dhanam_tier: pro
        prices: { MXN: { monthly: 30000 } }
        features:
          - "f1"
          - "f2"
          - "f3"
          - "f4"
  widget:
    name: Widget
    tiers:
      small:
        dhanam_tier: essentials
        prices: { MXN: { monthly: 20000 } }
        features:
          - "f1"
      large:
        dhanam_tier: pro
        prices: { MXN: { monthly: 60000 } }
        features:
          - "f1"
          - "f2"
coupons:
  intro_mx:
    percent_off: 50
    duration: repeating
    duration_months: 12
    products: [acme]
"""


def _load(tmp: Path, body: str) -> dict:
    p = tmp / "catalog.yaml"
    p.write_text(body)
    return _load_catalog_from_yaml(str(p))


class TestAuditTierGaps:
    def test_detects_cannibalization_and_healthy(self, tmp_path: Path) -> None:
        catalog = _load(tmp_path, _SAMPLE_CATALOG)
        findings = audit_tier_gaps(catalog, currency="MXN")
        # 2 products, 1 transition each = 2 findings.
        assert len(findings) == 2
        by_product = {f.product_slug: f for f in findings}
        # acme: 3x jump, +1 feature => cannibalization_risk
        assert by_product["acme"].severity == "cannibalization_risk"
        assert by_product["acme"].ratio == 3.0
        # widget: 3x jump, +1 feature => cannibalization_risk
        assert by_product["widget"].severity == "cannibalization_risk"

    def test_unpriced_tiers_are_skipped(self, tmp_path: Path) -> None:
        body = """
products:
  only_unpriced:
    name: X
    tiers:
      free:
        dhanam_tier: essentials
        prices: {}
        features: []
      paid:
        dhanam_tier: pro
        prices: { MXN: { monthly: 10000 } }
        features: []
"""
        catalog = _load(tmp_path, body)
        findings = audit_tier_gaps(catalog, currency="MXN")
        # Only one tier is priced; no transition to audit.
        assert findings == []


class TestAuditPromoStacks:
    def test_applies_deepest_coupon(self, tmp_path: Path) -> None:
        catalog = _load(tmp_path, _SAMPLE_CATALOG)
        findings = audit_promo_stacks(catalog, currency="MXN")
        acme_findings = [f for f in findings if f.product_slug == "acme"]
        assert len(acme_findings) == 2  # entry + pro
        for f in acme_findings:
            assert f.coupon == "intro_mx"
            assert f.total_discount_pct == pytest.approx(50.0, abs=0.1)

    def test_product_without_coupon_reports_none(self, tmp_path: Path) -> None:
        catalog = _load(tmp_path, _SAMPLE_CATALOG)
        findings = audit_promo_stacks(catalog, currency="MXN")
        widget_findings = [f for f in findings if f.product_slug == "widget"]
        assert len(widget_findings) == 2
        for f in widget_findings:
            assert f.coupon == "(none)"
            assert f.effective_monthly == f.list_monthly


# ============================================================================
# Tool interfaces (CatalogLoadTool, TierGap, PromoStack)
# ============================================================================


@pytest.mark.asyncio
class TestCatalogLoadTool:
    async def test_loads_from_local_path(self, tmp_path: Path) -> None:
        p = tmp_path / "cat.yaml"
        p.write_text(_SAMPLE_CATALOG)
        res = await CatalogLoadTool().execute(source=str(p))
        assert res.success is True
        assert set(res.data["products"]) == {"acme", "widget"}
        assert res.data["tier_count"] == 4
        assert res.data["coupons"] == ["intro_mx"]

    async def test_bad_path_returns_error(self, tmp_path: Path) -> None:
        res = await CatalogLoadTool().execute(source=str(tmp_path / "missing.yaml"))
        assert res.success is False
        assert "failed to load catalog" in (res.error or "")


@pytest.mark.asyncio
class TestCatalogTierGapTool:
    async def test_summary_counts_match_severity(self, tmp_path: Path) -> None:
        p = tmp_path / "cat.yaml"
        p.write_text(_SAMPLE_CATALOG)
        res = await CatalogTierGapTool().execute(source=str(p), currency="MXN")
        assert res.success
        assert res.data["total_transitions"] == 2
        assert res.data["cannibalization_risks"] == 2


@pytest.mark.asyncio
class TestCatalogPromoStackTool:
    async def test_reports_per_tier_findings(self, tmp_path: Path) -> None:
        p = tmp_path / "cat.yaml"
        p.write_text(_SAMPLE_CATALOG)
        res = await CatalogPromoStackTool().execute(source=str(p), currency="MXN")
        assert res.success
        assert len(res.data["findings"]) == 4  # 2 products × 2 tiers


@pytest.mark.asyncio
class TestCompetitorPriceLookupTool:
    async def test_happy_path_returns_body(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url == httpx.URL("https://comp.test/pricing")
            assert "Selva" in request.headers["user-agent"]
            return httpx.Response(200, text="<h1>$99/mo</h1>" * 100)

        transport = httpx.MockTransport(handler)
        import httpx as _httpx

        real_async_client = _httpx.AsyncClient

        # Monkey-patch AsyncClient to use our transport for this test only.
        class PatchedClient(real_async_client):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = transport
                super().__init__(*args, **kwargs)

        _httpx.AsyncClient = PatchedClient  # type: ignore[assignment]
        try:
            with patch(
                "selva_tools.builtins.pricing_intel._build_safe_request_kwargs",
                side_effect=_bypass_safe_request_kwargs,
            ):
                res = await CompetitorPriceLookupTool().execute(url="https://comp.test/pricing")
            assert res.success
            assert res.data["status_code"] == 200
            assert "$99" in res.data["body"]
        finally:
            _httpx.AsyncClient = real_async_client  # type: ignore[assignment]

    async def test_rejects_non_https(self) -> None:
        res = await CompetitorPriceLookupTool().execute(url="ftp://x.test/")
        assert res.success is False
        assert "http" in (res.error or "").lower()

    async def test_5xx_returns_failure(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="server down")

        transport = httpx.MockTransport(handler)
        import httpx as _httpx

        real = _httpx.AsyncClient

        class PatchedClient(real):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = transport
                super().__init__(*args, **kwargs)

        _httpx.AsyncClient = PatchedClient  # type: ignore[assignment]
        try:
            with patch(
                "selva_tools.builtins.pricing_intel._build_safe_request_kwargs",
                side_effect=_bypass_safe_request_kwargs,
            ):
                res = await CompetitorPriceLookupTool().execute(url="https://comp.test/pricing")
            assert res.success is False
            assert res.data.get("status_code") == 503
        finally:
            _httpx.AsyncClient = real  # type: ignore[assignment]


# ============================================================================
# Finding dataclasses
# ============================================================================


def test_tier_gap_finding_round_trips_to_dict() -> None:
    f = TierGapFinding(
        product_slug="x",
        from_tier="a",
        to_tier="b",
        currency="MXN",
        from_monthly=1,
        to_monthly=2,
        ratio=2.0,
        feature_delta=1,
        severity="ok",
        note="healthy",
    )
    d = f.__dict__
    assert d["product_slug"] == "x"
    assert d["ratio"] == 2.0


def test_promo_stack_finding_round_trips_to_dict() -> None:
    f = PromoStackFinding(
        product_slug="x",
        tier_slug="pro",
        coupon="c1",
        currency="MXN",
        list_monthly=10000,
        effective_monthly=6000,
        total_discount_pct=40.0,
        severity="ok",
        note="healthy",
    )
    d = f.__dict__
    assert d["coupon"] == "c1"
    assert d["total_discount_pct"] == 40.0
