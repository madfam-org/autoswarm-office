"""Pydantic models for Phynd-CRM API responses."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PhyndContact(BaseModel):
    id: str
    name: str
    email: str | None = None
    phone: str | None = None
    company: str | None = None
    status: str = "active"


class PhyndLead(BaseModel):
    id: str
    contact_id: str
    stage_id: str
    stage_name: str = ""
    score: float | None = None
    status: str = "open"
    created_at: str | None = None


class PhyndActivity(BaseModel):
    id: str
    type: str  # email, call, meeting, task
    title: str
    description: str = ""
    entity_type: str = ""  # contact, lead, opportunity
    entity_id: str = ""
    status: str = "pending"
    due_date: str | None = None
    completed_at: str | None = None


class PhyndUnifiedProfile(BaseModel):
    contact: PhyndContact
    leads: list[PhyndLead] = Field(default_factory=list)
    activities: list[PhyndActivity] = Field(default_factory=list)
    billing_status: str | None = None
    total_revenue: float | None = None


class PhyndLeadScore(BaseModel):
    lead_id: str
    score: float
    factors: dict[str, float] = Field(default_factory=dict)
    recommendation: str = ""


class PhyndDashboard(BaseModel):
    total_contacts: int = 0
    total_leads: int = 0
    open_activities: int = 0
    pipeline_value: float = 0.0
    conversion_rate: float | None = None
