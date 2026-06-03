# Autonomous Cleanroom Protocol (ACP)

**Document Status:** Approved Feature  
**Target Platform:** selva-office (Selva Instance)

## Core Ethos
**High Tech, Deep Roots** — Emancipating utility from proprietary walled gardens via digitally sovereign reverse-engineering.

## 1. Executive Summary

The Autonomous Cleanroom Protocol (ACP) is a multi-agent orchestration pipeline designed to strip intellectual property from existing digital products and autonomously reconstruct them from scratch. By strictly isolating "dirty" observation agents from "clean" engineering swarms across an automated airgap, the ACP ensures legal defensibility and technical sovereignty. This enables the rapid commoditization of rented SaaS utilities into owned, self-hostable infrastructure.

## 2. Strategic Alignment

This feature directly supports the overarching goal of digital sovereignty. By utilizing our autonomous agent swarms to perform cleanroom reverse-engineering, we eliminate dependencies on external, proprietary ecosystems. The output is natively designed for deployment on owned, bare-metal server infrastructure, reinforcing a decentralized and resilient operational model.

## 3. Architecture & Agent Roles

The ACP requires a strict, four-stage pipeline utilizing containerized, ephemeral agent environments to guarantee absolute memory hygiene.

### Phase I: The Analyst (Dirty Environment)
*   **Function:** Interacts directly with the target proprietary system (API, SaaS UI, documentation).
*   **Directives:** Observe and document behavior, input/output structures, state changes, and user flows. Absolutely no documentation of underlying implementation, variable names, or algorithmic choices.
*   **Output:** A comprehensive Product Requirements Document (PRD) and a suite of Black-Box Tests.

### Phase II: The Sanitizer (The Airgap)
*   **Function:** A rigid, deterministic parser combined with a highly constrained LLM auditor.
*   **Directives:** Audit the Analyst's PRD. Flag, redact, and scrub any residual proprietary terminology, architectural hints, or implementation details.
*   **Output:** A sterilized, purely functional specification.

### Phase III: Architect & Engineer Swarm (Clean Environment)
*   **Function:** The generative build team.
*   **Directives:** Construct the product based solely on the sterilized functional spec. Master prompts must explicitly enforce divergent thinking (forcing alternative data structures, novel mathematical approaches, and distinct design patterns) to bypass latent LLM pre-training biases that might inadvertently recreate standard proprietary algorithms.
*   **Output:** Novel, optimized source code targeting open-source best practices.

### Phase IV: The QA Oracle (Validation Loop)
*   **Function:** Closes the recursive deployment loop.
*   **Directives:** Compile the Clean Swarm's output and run it against the Analyst's Black-Box Tests. Report failures back to the Clean Swarm for iteration until 100% feature parity is achieved.

## 4. Platform Integrations & Infrastructure Dependencies

To operate securely and efficiently within our existing ecosystem, the ACP hooks into the following internal infrastructure:

*   **Enclii Integration (Deployment & Hygiene):** The agentic environments must be deployed via Enclii. The "Dirty" and "Clean" environments must operate in strictly isolated, containerized pods on bare-metal hardware. Upon completion of a cleanroom cycle, Enclii must completely tear down and destroy the containers to ensure zero cross-contamination of memory or state for future runs.
*   **Janua Integration (Authentication & Authorization):** Access to trigger an ACP event must be strictly governed by Janua. Given the legal and strategic sensitivity of reverse-engineering operations, Enterprise-grade SSO and rigorous Role-Based Access Control (RBAC) are required to track which authorized user initiated a specific cleanroom protocol.

## 5. Known Limitations & Mitigations

*   **LLM Pre-training Contamination:** As models are trained on the open internet, a "clean" agent might accidentally recreate a proprietary algorithm purely from its training weights.
    *   *Mitigation:* The divergent thinking constraint in Phase III is mandatory. The QA Oracle should ideally include a static analysis check to flag overly standard implementations of complex logic.
*   **Context Leakage:** Failure of the Sanitizer (Phase II) compromises the entire cleanroom defense.
    *   *Mitigation:* The Sanitizer's logs must be immutable and manually auditable to prove the airgap was maintained during the generation of any specific product.

## 6. Hermes Integration (Continuous Learning)

The ACP pipeline has been extended with the following capabilities inspired by the `NousResearch/hermes-agent` architecture:

*   **Procedural Skill Compilation:** On every successful Phase IV validation, the QA Oracle invokes the `madfam_inference` LLM router to synthesize the Phase III output into a standalone Python `.py` Playbook Skill, stored in the `selva-skills` registry. Future swarms can load these skills directly, reducing both context overhead and generation time for repeated engineering patterns.
*   **FTS5 Episodic Memory:** All pipeline events are archived into an SQLite WAL database (`selva_state.db`) with FTS5 virtual tables, enabling sub-millisecond full-text recall across all historical ACP runs.
*   **Multi-Channel Operator Gateway:** Human operators can trigger ACP runs and query swarm status via Telegram and Discord slash commands, eliminating dashboard dependency during mobile/field operations.
*   **MCP Dynamic Tooling:** The Phase I Analyst bootstraps Model Context Protocol servers (Tavily search, GitHub, filesystem) in its RPC subprocess, enabling dynamic tool expansion without container rebuilds.
*   **Dialectic User Profiling:** The `HonchoProfiler` maintains per-operator behavioral profiles, injecting preference context into swarm system prompts for personalized output quality.

**Operations:** See [`docs/HERMES_OPERATIONS.md`](./HERMES_OPERATIONS.md) for full deployment steps.

