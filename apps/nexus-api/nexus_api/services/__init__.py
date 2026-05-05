"""Domain services — business logic that orchestrates ORM models.

Routers stay thin: parse input, dispatch to a service, format response.
Services own the state-machine logic so the same operation can be
exercised from multiple call sites (REST, worker, batch script) with
the same invariants.
"""
