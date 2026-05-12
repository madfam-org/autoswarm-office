"""Built-in probe stages.

Each stage is a small class with ``name`` and ``async def run(ctx)``.
Import and compose them in the order you want them run.

The shipped default pipeline (see ``revenue_loop_probe.cli.default_pipeline``):

    1. CrmHotLeadStep        — creates or fetches a synthetic hot lead
    2. DraftStep             — hits the draft-email endpoint
    3. EmailSendStep         — sends (dry-run by default) the drafted email
    4. StripeWebhookStep     — fires a synthetic Stripe webhook into Dhanam
    5. DhanamBillingStep     — asserts the billing event landed
    6. PhyndAttributionStep  — asserts PhyndCRM credited the source agent
"""

from .crm import CrmHotLeadStep
from .drafter import DraftStep
from .email_send import EmailSendStep
from .stripe_webhook import StripeWebhookStep
from .dhanam_billing import DhanamBillingStep
from .phynd_attribution import PhyndAttributionStep

__all__ = [
    "CrmHotLeadStep",
    "DraftStep",
    "EmailSendStep",
    "StripeWebhookStep",
    "DhanamBillingStep",
    "PhyndAttributionStep",
]
