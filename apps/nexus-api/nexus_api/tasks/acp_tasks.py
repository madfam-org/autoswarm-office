import logging

from ..celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3)
def run_acp_workflow_task(self, target_url: str):
    """Celery task to orchestrate the ACP cycle.

    Executes the LangGraph Phase I Analyst workflow.

    SSRF defense-in-depth (Phase 1): re-validate the URL at task-start
    time using the same SSRF check the gateway uses at admission. This
    narrows the DNS-rebinding window from minutes (queue dwell time +
    workflow setup) to seconds (Celery dequeue → re-resolve). The
    workflow node still depends on browser/HTTP client behavior for page
    rendering. The URL is revalidated at task start; remaining browser-path
    hardening is tracked as a follow-up in the Phase 2 queue.
    """
    logger.info("Executing background ACP dirty analyst task for %s", target_url)
    try:
        # Re-run the SSRF gate. Importing here (not at module load) keeps
        # the worker process startup cheap and avoids circular imports.
        from ..routers.gateway import _validate_webhook_url

        target_url = _validate_webhook_url(target_url)
    except Exception as exc:
        logger.error(
            "ACP task refused: URL %s failed re-validation at task start "
            "(possible DNS rebinding or queue-time URL change): %s",
            target_url,
            exc,
        )
        # Don't retry — the URL is bad. Permanent failure.
        return {"error": "url_validation_failed", "detail": str(exc)}

    try:
        from selva_workflows.acp_analyst import ACPAnalystNode

        node = ACPAnalystNode(target_url=target_url)
        result = node.run()
        logger.info("Phase I Analyst complete. PRD length: %d", len(result.get("prd", "")))
        return result
    except Exception as exc:
        logger.error("Error in ACP Analyst workflow for %s: %s", target_url, exc)
        raise self.retry(exc=exc, countdown=60) from exc
