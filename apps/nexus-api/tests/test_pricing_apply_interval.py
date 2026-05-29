"""Regression: Dhanam BillingInterval expects monthly/yearly, not month/year."""

from nexus_api.services.pricing_apply import _interval_from_preview


def test_interval_from_preview_monthly_aliases():
    assert _interval_from_preview({"interval": "monthly"}) == "monthly"
    assert _interval_from_preview({"interval": "month"}) == "monthly"
    assert _interval_from_preview({}) == "monthly"


def test_interval_from_preview_yearly_aliases():
    assert _interval_from_preview({"interval": "yearly"}) == "yearly"
    assert _interval_from_preview({"interval": "year"}) == "yearly"
    assert _interval_from_preview({"interval": "annual"}) == "yearly"
