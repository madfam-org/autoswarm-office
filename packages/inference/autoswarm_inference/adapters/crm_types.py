"""Pydantic models for Phyne-CRM API responses."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PhyneContact(BaseModel):
    id: str
    name: str
    email: str | None = None
    phone: str | None = None
    company: str | None = None
    status: str = "active"


class PhyneLead(BaseModel):
    id: str
    contact_id: str
    stage_id: str
    stage_name: str = ""
    score: float | None = None
    status: str = "open"
    created_at: str | None = None


class PhyneActivity(BaseModel):
    id: str
    type: str  # email, call, meeting, task
    title: str
    description: str = ""
    entity_type: str = ""  # contact, lead, opportunity
    entity_id: str = ""
    status: str = "pending"
    due_date: str | None = None
    completed_at: str | None = None


class PhyneUnifiedProfile(BaseModel):
    contact: PhyneContact
    leads: list[PhyneLead] = Field(default_factory=list)
    activities: list[PhyneActivity] = Field(default_factory=list)
    billing_status: str | None = None
    total_revenue: float | None = None


class PhyneLeadScore(BaseModel):
    lead_id: str
    score: float
    factors: dict[str, float] = Field(default_factory=dict)
    recommendation: str = ""


class PhyneDashboard(BaseModel):
    total_contacts: int = 0
    total_leads: int = 0
    open_activities: int = 0
    pipeline_value: float = 0.0
    conversion_rate: float | None = None
