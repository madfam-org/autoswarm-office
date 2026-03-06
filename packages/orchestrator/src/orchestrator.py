"""Central swarm orchestrator coordinating agents, departments, and task dispatch."""

from __future__ import annotations

import uuid

from .compute_tokens import ComputeTokenManager
from .draft import DRAFT_COST, draft_agent_role, generate_agent_name
from .synergy import SynergyCalculator
from .types import AgentConfig, AgentRole, AgentStatus, DepartmentConfig, SwarmTask


class SwarmOrchestrator:
    """Orchestrates a swarm of agents across departments.

    Responsibilities:
      - Agent drafting with compute-token budget enforcement
      - Department assignment with capacity validation
      - Task dispatch with synergy bonus calculation
      - Agent lifecycle management (status tracking)
    """

    def __init__(
        self,
        agents: dict[str, AgentConfig] | None = None,
        departments: dict[str, DepartmentConfig] | None = None,
        synergy_calculator: SynergyCalculator | None = None,
        token_manager: ComputeTokenManager | None = None,
    ) -> None:
        self.agents: dict[str, AgentConfig] = agents if agents is not None else {}
        self.departments: dict[str, DepartmentConfig] = (
            departments if departments is not None else {}
        )
        self.synergy_calculator = synergy_calculator or SynergyCalculator()
        self.token_manager = token_manager or ComputeTokenManager()

    def draft_agent(
        self,
        role: AgentRole | None = None,
        name: str | None = None,
    ) -> AgentConfig:
        """Draft a new agent into the swarm.

        Consumes ``DRAFT_COST`` compute tokens.  If *role* is ``None``
        it is selected via weighted random choice.  If *name* is ``None``
        a thematic name is generated.

        Raises:
            ValueError: If the compute-token budget is insufficient.
        """
        if not self.token_manager.can_afford("draft_agent"):
            raise ValueError(
                f"Cannot draft agent: requires {DRAFT_COST} compute tokens, "
                f"only {self.token_manager.remaining} remaining"
            )

        existing_roles = [a.role for a in self.agents.values()]
        selected_role = draft_agent_role(existing_roles, preference=role)
        agent_name = name if name is not None else generate_agent_name(selected_role)
        agent_id = str(uuid.uuid4())

        agent = AgentConfig(
            id=agent_id,
            name=agent_name,
            role=selected_role,
        )

        self.token_manager.deduct("draft_agent")
        self.agents[agent_id] = agent
        return agent

    def assign_to_department(self, agent_id: str, department_id: str) -> None:
        """Assign an agent to a department.

        Raises:
            KeyError: If the agent or department does not exist.
            ValueError: If the department has reached its agent capacity.
        """
        if agent_id not in self.agents:
            raise KeyError(f"Agent '{agent_id}' not found")
        if department_id not in self.departments:
            raise KeyError(f"Department '{department_id}' not found")

        dept = self.departments[department_id]
        agent = self.agents[agent_id]

        if len(dept.agent_ids) >= dept.max_agents:
            raise ValueError(
                f"Department '{dept.name}' is at capacity "
                f"({dept.max_agents} agents)"
            )

        # Remove from current department if assigned
        if agent.department_id and agent.department_id in self.departments:
            old_dept = self.departments[agent.department_id]
            if agent_id in old_dept.agent_ids:
                old_dept.agent_ids.remove(agent_id)

        dept.agent_ids.append(agent_id)
        agent.department_id = department_id

    def dispatch_task(self, task: SwarmTask) -> float:
        """Dispatch a task to assigned agents and return the effective synergy multiplier.

        Validates that all assigned agents exist, deducts compute tokens,
        calculates synergy bonuses from the agents' role composition, and
        returns the cumulative multiplier.

        Raises:
            KeyError: If any assigned agent does not exist.
            ValueError: If the compute-token budget is insufficient.
        """
        for aid in task.assigned_agent_ids:
            if aid not in self.agents:
                raise KeyError(f"Assigned agent '{aid}' not found")

        if not self.token_manager.can_afford("dispatch_task"):
            raise ValueError(
                f"Cannot dispatch task: requires "
                f"{ComputeTokenManager.COST_TABLE['dispatch_task']} compute tokens, "
                f"only {self.token_manager.remaining} remaining"
            )

        self.token_manager.deduct("dispatch_task")

        roles = [self.agents[aid].role for aid in task.assigned_agent_ids]
        multiplier = self.synergy_calculator.get_effective_multiplier(roles)

        task.status = "dispatched"
        for aid in task.assigned_agent_ids:
            self.agents[aid].status = AgentStatus.WORKING

        return multiplier

    def get_department_agents(self, department_id: str) -> list[AgentConfig]:
        """Return all agents assigned to *department_id*.

        Raises:
            KeyError: If the department does not exist.
        """
        if department_id not in self.departments:
            raise KeyError(f"Department '{department_id}' not found")
        dept = self.departments[department_id]
        return [self.agents[aid] for aid in dept.agent_ids if aid in self.agents]

    def get_agent_status(self, agent_id: str) -> AgentStatus:
        """Return the current status of an agent.

        Raises:
            KeyError: If the agent does not exist.
        """
        if agent_id not in self.agents:
            raise KeyError(f"Agent '{agent_id}' not found")
        return self.agents[agent_id].status

    def update_agent_status(self, agent_id: str, status: AgentStatus) -> None:
        """Update the status of an agent.

        Raises:
            KeyError: If the agent does not exist.
        """
        if agent_id not in self.agents:
            raise KeyError(f"Agent '{agent_id}' not found")
        self.agents[agent_id].status = status
