"""Batch processing node handler — splits work and runs items in parallel."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from typing import Any

from ..schema import BatchAggregateStrategy, NodeDefinition

logger = logging.getLogger(__name__)


class BatchNodeHandler:
    """Handles execution of a 'batch' node.

    Splits ``state[batch_split_key]`` into items, runs each through a
    delegate node function in parallel (bounded by ``max_parallel``),
    and aggregates results according to the chosen strategy.
    """

    def __init__(
        self,
        node: NodeDefinition,
        delegate_fn: Any = None,
    ) -> None:
        self.node = node
        self._delegate_fn = delegate_fn

    def set_delegate_fn(self, fn: Any) -> None:
        self._delegate_fn = fn

    def build_node_fn(self) -> Any:
        node = self.node
        delegate_fn = self._delegate_fn

        async def batch_node(state: dict) -> dict:
            split_key = node.batch_split_key
            if not split_key or split_key not in state:
                logger.warning(
                    "Batch node '%s': split key '%s' not found in state",
                    node.id,
                    split_key,
                )
                return {**state, "current_node_id": node.id}

            items = state[split_key]
            if not isinstance(items, list):
                logger.warning(
                    "Batch node '%s': state['%s'] is not a list",
                    node.id,
                    split_key,
                )
                return {**state, "current_node_id": node.id}

            if not delegate_fn:
                logger.warning("Batch node '%s': no delegate function set", node.id)
                return {
                    **state,
                    "current_node_id": node.id,
                    "batch_results": items,
                }

            semaphore = asyncio.Semaphore(node.max_parallel)

            async def process_item(item: Any) -> dict:
                async with semaphore:
                    item_state = {**state, split_key: item, "batch_item": item}
                    result = delegate_fn(item_state)
                    if asyncio.iscoroutine(result):
                        result = await result
                    return result

            results = await asyncio.gather(
                *[process_item(item) for item in items],
                return_exceptions=True,
            )

            # Separate successes from errors. ``return_exceptions=True`` may
            # return any ``BaseException``, so guard against the wider type
            # (mypy widens to ``dict | BaseException``).
            successes: list[dict] = []
            errors: list[str] = []
            for r in results:
                if isinstance(r, BaseException):
                    errors.append(str(r))
                else:
                    successes.append(r)

            aggregated = _aggregate(successes, node.batch_aggregate_strategy)

            return {
                **state,
                "current_node_id": node.id,
                "batch_results": aggregated,
                "batch_errors": errors,
                "batch_total": len(items),
                "batch_succeeded": len(successes),
                "batch_failed": len(errors),
            }

        batch_node.__name__ = f"batch_{node.id}"
        return batch_node


def _aggregate(results: list[dict], strategy: BatchAggregateStrategy) -> Any:
    """Aggregate batch results according to the chosen strategy."""
    if not results:
        return []

    if strategy == BatchAggregateStrategy.COLLECT:
        return results

    if strategy == BatchAggregateStrategy.MERGE:
        merged: dict = {}
        for r in results:
            if isinstance(r, dict):
                merged.update(r)
        return merged

    if strategy == BatchAggregateStrategy.VOTE:
        # Vote on the 'result' key across all results
        votes: list[str] = []
        for r in results:
            if isinstance(r, dict) and "result" in r:
                votes.append(str(r["result"]))
        if not votes:
            return results
        counter = Counter(votes)
        winner, _ = counter.most_common(1)[0]
        return {"result": winner, "votes": dict(counter)}

    return results
