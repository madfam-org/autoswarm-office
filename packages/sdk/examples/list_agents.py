"""List all agents and their statuses.

Usage:
    export SELVA_API_URL=http://localhost:4300
    export SELVA_TOKEN=<your-token>
    python list_agents.py
"""

import asyncio

from selva_sdk import Selva


async def main() -> None:
    client = Selva()

    agents = await client.list_agents()
    print(f"Found {len(agents)} agents:\n")
    for agent in agents:
        print(f"  {agent.name:20s} | {agent.role:15s} | {agent.status}")


if __name__ == "__main__":
    asyncio.run(main())
