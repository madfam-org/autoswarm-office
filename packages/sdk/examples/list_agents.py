"""List all agents and their statuses.

Usage:
    export AUTOSWARM_API_URL=http://localhost:4300
    export AUTOSWARM_TOKEN=<your-token>
    python list_agents.py
"""

import asyncio

from selva_sdk import AutoSwarm


async def main() -> None:
    client = AutoSwarm()

    agents = await client.list_agents()
    print(f"Found {len(agents)} agents:\n")
    for agent in agents:
        print(f"  {agent.name:20s} | {agent.role:15s} | {agent.status}")


if __name__ == "__main__":
    asyncio.run(main())
