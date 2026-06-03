/**
 * Demo simulation engine.
 *
 * Populates the Colyseus state with demo agents and runs a periodic loop
 * that cycles agents through idle → working → waiting_approval → idle.
 * If a human approves/denies within the waiting window, the agent reacts
 * immediately; otherwise it auto-resolves after ~15s.
 */

import {
  OfficeStateSchema,
  AgentSchema,
  DepartmentSchema,
} from "../schema/OfficeState";
import { addSystemMessage } from "../handlers/chat";
import { DEMO_AGENTS, DEMO_TASK_DESCRIPTIONS } from "./demo-agents";
import { createLogger } from "@selva/config/logging";

const logger = createLogger({ service: "colyseus" }).child({ component: "DemoSimulator" });

/** How often (ms) to attempt starting a new task cycle. */
const CYCLE_INTERVAL_MS = 12_000;
/** How long (ms) an agent stays "working" before requesting approval. */
const WORK_DURATION_MS = 15_000;
/** How long (ms) to wait for human approval before auto-approving. */
const AUTO_APPROVE_MS = 15_000;

function randomItem<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)];
}

function randomBetween(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

export class DemoSimulator {
  private state: OfficeStateSchema;
  private cycleTimer: ReturnType<typeof setInterval> | null = null;
  private pendingTimers: Set<ReturnType<typeof setTimeout>> = new Set();
  private disposed = false;

  constructor(state: OfficeStateSchema) {
    this.state = state;
  }

  start(): void {
    this.populateAgents();

    // Start simulation cycle
    this.cycleTimer = setInterval(() => {
      if (!this.disposed) this.tryStartTask();
    }, CYCLE_INTERVAL_MS + randomBetween(-2000, 2000));

    // Kick off a first task quickly so the demo isn't empty
    const firstTimer = setTimeout(() => {
      if (!this.disposed) this.tryStartTask();
    }, 3000);
    this.pendingTimers.add(firstTimer);

    logger.info("Demo simulation started");
  }

  stop(): void {
    this.disposed = true;
    if (this.cycleTimer) {
      clearInterval(this.cycleTimer);
      this.cycleTimer = null;
    }
    for (const timer of this.pendingTimers) {
      clearTimeout(timer);
    }
    this.pendingTimers.clear();
    logger.info("Demo simulation stopped");
  }

  /**
   * Handle a demo approval from a human player.
   * Returns true if a matching agent was found and resolved.
   */
  resolveApproval(agentId: string, result: "approved" | "denied"): boolean {
    const agent = this.findAgent(agentId);
    if (!agent || agent.status !== "waiting_approval") return false;

    const verb = result === "approved" ? "approved" : "denied";
    agent.status = "idle";
    agent.currentTaskId = "";
    agent.currentTaskDescription = "";
    if (this.state.pendingApprovalCount > 0) {
      this.state.pendingApprovalCount -= 1;
    }
    addSystemMessage(this.state, `${agent.name}'s task was ${verb}`);
    return true;
  }

  // ---------------------------------------------------------------------------

  private populateAgents(): void {
    for (const def of DEMO_AGENTS) {
      const dept = this.state.departments.get(def.departmentId);
      if (!dept) continue;

      const agent = new AgentSchema();
      agent.id = def.id;
      agent.name = def.name;
      agent.role = def.role;
      agent.status = "idle";
      agent.level = def.level;
      agent.x = dept.x + 48 + (dept.agents.length % 3) * 48;
      agent.y = dept.y + 48 + Math.floor(dept.agents.length / 3) * 48;
      agent.currentTaskId = "";
      agent.currentTaskDescription = "";
      agent.departmentId = def.departmentId;
      for (const skill of def.skills) {
        agent.skills.push(skill);
      }
      dept.agents.push(agent);
    }
    logger.info({ count: DEMO_AGENTS.length }, "Demo agents populated");
  }

  private tryStartTask(): void {
    // Find an idle agent
    const idleAgents: AgentSchema[] = [];
    this.state.departments.forEach((dept: DepartmentSchema) => {
      for (let i = 0; i < dept.agents.length; i++) {
        const a = dept.agents.at(i);
        if (a && a.status === "idle") idleAgents.push(a);
      }
    });

    if (idleAgents.length === 0) return;

    const agent = randomItem(idleAgents);
    const description = randomItem(DEMO_TASK_DESCRIPTIONS);
    const taskId = `demo-task-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;

    // → working
    agent.status = "working";
    agent.currentTaskId = taskId;
    agent.currentTaskDescription = description;
    addSystemMessage(this.state, `${agent.name} started working on: ${description}`);

    // After WORK_DURATION → waiting_approval
    const workTimer = setTimeout(() => {
      this.pendingTimers.delete(workTimer);
      if (this.disposed) return;
      if (agent.status !== "working" || agent.currentTaskId !== taskId) return;

      agent.status = "waiting_approval";
      this.state.pendingApprovalCount += 1;
      addSystemMessage(this.state, `${agent.name} is waiting for approval`);

      // Auto-approve after AUTO_APPROVE_MS if still waiting
      const approveTimer = setTimeout(() => {
        this.pendingTimers.delete(approveTimer);
        if (this.disposed) return;
        if (agent.status !== "waiting_approval" || agent.currentTaskId !== taskId) return;

        agent.status = "idle";
        agent.currentTaskId = "";
        agent.currentTaskDescription = "";
        if (this.state.pendingApprovalCount > 0) {
          this.state.pendingApprovalCount -= 1;
        }
        addSystemMessage(this.state, `${agent.name}'s task was auto-approved`);
      }, AUTO_APPROVE_MS);
      this.pendingTimers.add(approveTimer);
    }, WORK_DURATION_MS + randomBetween(-3000, 3000));
    this.pendingTimers.add(workTimer);
  }

  private findAgent(agentId: string): AgentSchema | null {
    let found: AgentSchema | null = null;
    this.state.departments.forEach((dept: DepartmentSchema) => {
      if (found) return;
      for (let i = 0; i < dept.agents.length; i++) {
        const a = dept.agents.at(i);
        if (a && a.id === agentId) {
          found = a;
          return;
        }
      }
    });
    return found;
  }
}
