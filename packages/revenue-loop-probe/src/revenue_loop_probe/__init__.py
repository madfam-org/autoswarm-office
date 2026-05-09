"""Revenue-loop synthetic probe for the MADFAM ecosystem.

Exercises the end-to-end autonomous revenue flywheel (per
`project_autonomous_loop_status` memory):

    CRM lead --> draft (LLM) --> email send --> Stripe webhook -->
    Dhanam billing event --> PhyndCRM attribution.

Pages when any stage breaks. Safe by default: stages whose endpoint is not
configured are *skipped* (not failed), so a partially-deployed env doesn't
page.

Run via `revenue-loop-probe` CLI or import ``RevenueLoopProbe`` directly.
"""

from .probe import (
    ProbeContext,
    ProbeReport,
    ProbeStep,
    RevenueLoopProbe,
    StageResult,
    StageStatus,
)

__all__ = [
    "ProbeContext",
    "ProbeReport",
    "ProbeStep",
    "RevenueLoopProbe",
    "StageResult",
    "StageStatus",
]

__version__ = "0.1.0"
