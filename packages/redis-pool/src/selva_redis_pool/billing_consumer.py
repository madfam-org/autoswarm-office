"""
Billing event consumer for the MADFAM ecosystem event bus.

Consumes billing and KYC events from the shared Redis Stream
``selva:billing-events`` published by Dhanam. Uses XREADGROUP
with consumer group ``selva-consumers`` for durable delivery.

Events:
    billing.subscription.created   -- New subscription activated
    billing.subscription.cancelled -- Subscription cancelled
    billing.payment.succeeded      -- Payment received
    billing.payment.failed         -- Payment failed
    kyc.verified                   -- KYC verification passed
    kyc.rejected                   -- KYC verification rejected

Usage:
    # As a standalone worker entry point:
    python -m selva_redis_pool.billing_consumer

    # Or start from application code:
    consumer = BillingEventConsumer()
    await consumer.run()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import socket
from typing import Any

from .pool import get_redis_pool

logger = logging.getLogger(__name__)

STREAM_KEY = os.getenv("BILLING_STREAM_KEY", "selva:billing-events")
DLQ_KEY = "selva:billing-dlq"
GROUP_NAME = "selva-consumers"
MAX_RETRIES = 3
BLOCK_MS = 5000  # 5 seconds
BATCH_SIZE = 10


def _default_consumer_name() -> str:
    """Generate a consumer name from hostname and PID."""
    return f"selva-{socket.gethostname()}-{os.getpid()}"


class BillingEventConsumer:
    """Consumes billing events from the MADFAM event bus via Redis Streams."""

    def __init__(
        self,
        stream_key: str = STREAM_KEY,
        group_name: str = GROUP_NAME,
        consumer_name: str | None = None,
    ) -> None:
        self._stream_key = stream_key
        self._group_name = group_name
        self._consumer_name = consumer_name or _default_consumer_name()
        self._running = True

    async def ensure_group(self) -> None:
        """Create the consumer group if it does not already exist."""
        pool = get_redis_pool()
        client = await pool.client()
        try:
            await client.xgroup_create(self._stream_key, self._group_name, id="0", mkstream=True)
            logger.info(
                "Created consumer group '%s' on '%s'",
                self._group_name,
                self._stream_key,
            )
        except Exception as exc:
            if "BUSYGROUP" in str(exc):
                pass  # Group already exists
            else:
                raise

    async def run(self) -> None:
        """Main consumer loop. Reads, processes, acks, and handles DLQ."""
        await self.ensure_group()
        logger.info(
            "Billing consumer started: stream=%s group=%s consumer=%s",
            self._stream_key,
            self._group_name,
            self._consumer_name,
        )

        pool = get_redis_pool()

        while self._running:
            try:
                client = await pool.client()
                results = await client.xreadgroup(
                    groupname=self._group_name,
                    consumername=self._consumer_name,
                    streams={self._stream_key: ">"},
                    count=BATCH_SIZE,
                    block=BLOCK_MS,
                )

                if not results:
                    continue

                for _stream_name, messages in results:
                    for msg_id, fields in messages:
                        await self._process_message(msg_id, fields)

            except asyncio.CancelledError:
                logger.info("Billing consumer cancelled, shutting down")
                break
            except Exception as exc:
                logger.error("Billing consumer read error: %s", exc)
                await asyncio.sleep(2)

        logger.info("Billing consumer stopped")

    async def _process_message(self, msg_id: str, fields: dict[Any, Any]) -> None:
        """Process a single stream message with retry/DLQ logic.

        ``fields`` may be keyed by ``str`` or ``bytes`` depending on whether
        the underlying Redis client was configured with ``decode_responses``;
        we accept both shapes defensively.
        """
        get_redis_pool()

        try:
            raw = fields.get("data") or fields.get(b"data", "")
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            event_data = json.loads(raw) if raw else fields
        except (json.JSONDecodeError, TypeError) as exc:
            logger.error("Bad billing event %s: %s", msg_id, exc)
            await self._ack(msg_id)
            return

        event_type = event_data.get("event_type", event_data.get("type", ""))

        try:
            self._handle_event(event_type, event_data)
            await self._ack(msg_id)
        except Exception as exc:
            retry_count = await self._get_retry_count(msg_id)
            if retry_count >= MAX_RETRIES:
                logger.warning(
                    "Billing event %s exhausted retries (%d), moving to DLQ: %s",
                    msg_id,
                    retry_count,
                    exc,
                )
                await self._move_to_dlq(msg_id, event_data, str(exc))
            else:
                logger.warning(
                    "Billing event %s processing failed (attempt %d/%d): %s",
                    msg_id,
                    retry_count + 1,
                    MAX_RETRIES,
                    exc,
                )
                # Do not ack -- message will be redelivered on next XREADGROUP
                # with pending entries list (PEL)

    def _handle_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Route the event to the appropriate handler."""
        handler_map = {
            "billing.subscription.created": self._on_subscription_created,
            "billing.subscription.cancelled": self._on_subscription_cancelled,
            "billing.payment.succeeded": self._on_payment_succeeded,
            "billing.payment.failed": self._on_payment_failed,
            "kyc.verified": self._on_kyc_verified,
            "kyc.rejected": self._on_kyc_rejected,
        }

        handler = handler_map.get(event_type)
        if handler:
            handler(data)
        else:
            logger.debug("Billing consumer ignoring event_type=%s", event_type)

    # ─── Event handlers ───────────────────────────────────────────────

    def _on_subscription_created(self, data: dict[str, Any]) -> None:
        """Log subscription creation for agent awareness.

        Agents can query subscription status to adjust behavior
        (e.g., unlocking premium task graphs for paid users).
        """
        logger.info(
            "Billing: subscription created user_id=%s plan=%s status=%s provider=%s",
            data.get("user_id"),
            data.get("plan"),
            data.get("status"),
            data.get("provider"),
        )

    def _on_subscription_cancelled(self, data: dict[str, Any]) -> None:
        logger.info(
            "Billing: subscription cancelled user_id=%s plan=%s reason=%s effective_at=%s",
            data.get("user_id"),
            data.get("plan"),
            data.get("reason"),
            data.get("effective_at"),
        )

    def _on_payment_succeeded(self, data: dict[str, Any]) -> None:
        logger.info(
            "Billing: payment succeeded user_id=%s amount=%s %s provider=%s invoice=%s",
            data.get("user_id"),
            data.get("amount"),
            data.get("currency"),
            data.get("provider"),
            data.get("invoice_id"),
        )

    def _on_payment_failed(self, data: dict[str, Any]) -> None:
        logger.warning(
            "Billing: payment failed user_id=%s amount=%s %s error=%s",
            data.get("user_id"),
            data.get("amount"),
            data.get("currency"),
            data.get("error_message"),
        )

    def _on_kyc_verified(self, data: dict[str, Any]) -> None:
        logger.info(
            "KYC: verified user_id=%s email=%s verification_id=%s",
            data.get("user_id"),
            data.get("email"),
            data.get("verification_id"),
        )

    def _on_kyc_rejected(self, data: dict[str, Any]) -> None:
        logger.warning(
            "KYC: rejected user_id=%s verification_id=%s reason=%s",
            data.get("user_id"),
            data.get("verification_id"),
            data.get("reason"),
        )

    # ─── Stream helpers ───────────────────────────────────────────────

    async def _ack(self, message_id: str) -> None:
        pool = get_redis_pool()
        await pool.execute_with_retry("xack", self._stream_key, self._group_name, message_id)

    async def _get_retry_count(self, message_id: str) -> int:
        pool = get_redis_pool()
        client = await pool.client()
        try:
            pending = await client.xpending_range(
                self._stream_key, self._group_name, message_id, message_id, 1
            )
            if pending:
                return int(pending[0].get("times_delivered", 0))
        except Exception:
            pass
        return 0

    async def _move_to_dlq(self, message_id: str, event_data: dict[str, Any], error: str) -> None:
        pool = get_redis_pool()
        dlq_data = json.dumps(
            {**event_data, "error": error, "original_id": message_id},
            default=str,
        )
        await pool.execute_with_retry("xadd", DLQ_KEY, {"data": dlq_data})
        await self._ack(message_id)
        logger.warning(
            "Billing event moved to DLQ: msg_id=%s event_type=%s",
            message_id,
            event_data.get("event_type", "?"),
        )

    def stop(self) -> None:
        """Signal the consumer to stop gracefully."""
        self._running = False


async def _main() -> None:
    """Entry point for running the billing consumer as a standalone worker."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    consumer = BillingEventConsumer()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, consumer.stop)

    await consumer.run()


if __name__ == "__main__":
    asyncio.run(_main())
