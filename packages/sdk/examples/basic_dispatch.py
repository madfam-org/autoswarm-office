"""Dispatch a coding task and wait for the result.

Usage:
    export AUTOSWARM_API_URL=http://localhost:4300
    export AUTOSWARM_TOKEN=<your-token>
    python basic_dispatch.py
"""

import asyncio

from selva_sdk import AutoSwarm


async def main() -> None:
    client = AutoSwarm()

    task = await client.dispatch(
        description="Refactor the auth middleware to use dependency injection",
        graph_type="coding",
    )
    print(f"Task dispatched: {task.id}")
    print(f"Status: {task.status}")

    result = await client.wait_for_task(task.id, timeout=120)
    print(f"Final status: {result.status}")
    if result.payload.get("result"):
        print(f"Result: {result.payload['result']}")


if __name__ == "__main__":
    asyncio.run(main())
