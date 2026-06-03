"""Dispatch a task using a custom workflow.

Usage:
    export SELVA_API_URL=http://localhost:4300
    export SELVA_TOKEN=<your-token>
    python custom_workflow.py <workflow-id>
"""

import asyncio
import sys

from selva_sdk import Selva


async def main(workflow_id: str) -> None:
    client = Selva()

    task = await client.dispatch(
        description="Process quarterly report data",
        graph_type="custom",
        workflow_id=workflow_id,
    )
    print(f"Custom workflow task dispatched: {task.id}")
    print(f"Workflow: {workflow_id}")
    print(f"Status: {task.status}")

    result = await client.wait_for_task(task.id, timeout=300)
    print(f"Final status: {result.status}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python custom_workflow.py <workflow-id>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
