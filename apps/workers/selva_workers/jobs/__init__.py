"""Background cron jobs run periodically by the worker process.

Each module here exposes ``async def run() -> dict`` which can be invoked:
- on a fixed cadence by the worker's housekeeping loop (see
  :func:`apps.workers.selva_workers.__main__._housekeeping_loop`)
- ad-hoc via Celery Beat for jobs that need to outlive worker restarts
  (provider_balance_probe falls into this category — the 15-min cadence
  is independent of any single task's lifecycle)
- by tests via direct ``await module.run()``

Jobs MUST be idempotent — the same run() invocation may be triggered
multiple times due to retry, beat double-fire, or operator-initiated
manual run.
"""
