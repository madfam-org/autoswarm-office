# Selva Competitive Benchmark — Virtual Office Platforms

> Last updated: April 2026
> Reference: [ro.am/virtual-office-platform](https://ro.am/virtual-office-platform)
>
> **Strategic layer (GTM, wedges, GA path):** see
> [COMMERCIAL_GA_STRATEGY_AND_IMPLEMENTATION_2026-06-22.md](./COMMERCIAL_GA_STRATEGY_AND_IMPLEMENTATION_2026-06-22.md).
> **Pricing SSOT:** [infra/pricing/selva-tiers.json](../infra/pricing/selva-tiers.json)
> (Tulana metered packs) — the seat-based figures in §Pricing below are legacy.

## Executive Summary

Selva is not a virtual office for humans pretending to be in the same room. **Selva is a virtual office where AI agents work autonomously, with humans supervising via a game-like interface.** This puts it in a fundamentally different category than Roam, Gather, or Kumospace — those platforms optimize for human-to-human presence; Selva optimizes for human-to-AI orchestration with autonomous execution.

No competitor has: a 10-agent AI workforce, autonomous task dispatch via CRM-driven playbooks, LLM inference with tool execution, a permission engine with HITL approval gates, or a Factory-as-a-Product phygital pipeline.

---

## Platform Comparison Matrix

### Competitors Analyzed

| # | Platform | Model | Pricing | Founded |
|---|----------|-------|---------|---------|
| 1 | **Roam** | Room-based presence map | $19.50/seat/mo | 2022 (Howard Lerman) |
| 2 | **Gather** | 2D pixel-art spatial | $7+/seat/mo (free tier) | 2020 |
| 3 | **Kumospace** | Photorealistic spatial | $16+/seat/mo | 2020 |
| 4 | **Sococo** | Top-down floor plan | $13.49-24.99/seat/mo | 2012 |
| 5 | **Teamflow** | Bubble-based UI | $0-30/seat/mo | 2020 |
| 6 | **oVice** | 2D avatar spatial | Contact sales | 2020 |
| 7 | **Spot** | Spatial with clean UI | Free-$16+/seat/mo | 2020 |
| 8 | **SoWork** | 2.5D spatial | $6-15/seat/mo | 2021 |
| 9 | **WorkAdventure** | Open-source 2D pixel | Free-$5+/seat/mo | 2020 |
| 10 | **Selva** | AI workforce + pixel-art office | $149-499/seat/mo (Selva tier) | 2025 (MADFAM) |

---

### 1. PRESENCE & OFFICE MAP

| Feature | Roam | Gather | Kumospace | Sococo | Teamflow | oVice | Spot | SoWork | WorkAdventure | **Selva** |
|---------|:----:|:------:|:---------:|:------:|:--------:|:-----:|:----:|:------:|:-------------:|:---------:|
| Full company visualization | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ⚠️ | ✅ | ✅ | ✅ |
| Real-time presence indicators | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Multi-floor / departments | ✅ | ✅ | ⚠️ | ✅ | ❌ | ✅ | ❌ | ⚠️ | ✅ | ✅ (4 biomes) |
| Proximity audio | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ (simple-peer) |
| Avatar customization | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ✅ | ✅ | ✅ (5 properties + companions) |
| Map editor | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ (in-browser tile editor) |
| Spotlight / search | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ (follow player, teleport) |
| Explorer mode | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ (Tab key, full map zoom) |
| Click-to-move pathfinding | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ (A* pathfinding) |
| **AI agents on map** | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ **(10 named agents with roles)** |

### 2. AI & AUTONOMOUS CAPABILITIES

| Feature | Roam | Gather | Others | **Selva** |
|---------|:----:|:------:|:------:|:---------:|
| AI agents with roles | ✅ (1 assistant) | ❌ | ❌ | ✅ **(10 agents, 4 departments)** |
| Autonomous task dispatch | ❌ | ❌ | ❌ | ✅ **(HeartbeatService + playbooks)** |
| LLM inference (multi-provider) | ❌ | ❌ | ❌ | ✅ **(Anthropic, DeepInfra, 8+ providers)** |
| AI note-taking | ✅ | ❌ | ❌ | ✅ (meeting graph) |
| AI assistant chat | ✅ | ❌ | ❌ | ✅ (per-agent chat) |
| Tool execution (70+ tools) | ❌ | ❌ | ❌ | ✅ **(email, git, SQL, HTTP, PDF, deploy, CRM, billing)** |
| Permission engine (HITL) | ❌ | ❌ | ❌ | ✅ **(PlaybookGuard + PermissionEngine)** |
| Code generation + PR creation | ❌ | ❌ | ❌ | ✅ **(coding graph with worktrees)** |
| Agent-to-Agent protocol (A2A) | ❌ | ❌ | ❌ | ✅ |
| Financial circuit breaker | ❌ | ❌ | ❌ | ✅ **($50/day per-org limit)** |
| Agent learning (RL + reflexion) | ❌ | ❌ | ❌ | ✅ **(Thompson Sampling + experience store)** |
| Custom YAML workflows | ❌ | ❌ | ❌ | ✅ **(visual workflow builder)** |

### 3. COLLABORATION & COMMUNICATION

| Feature | Roam | Gather | Kumospace | Sococo | Others | **Selva** |
|---------|:----:|:------:|:---------:|:------:|:------:|:---------:|
| Video conferencing | ✅ | ✅ | ✅ | ✅ (Zoom) | varies | ✅ (WebRTC proximity) |
| Screen sharing | ✅ | ✅ | ✅ | ✅ | varies | ✅ (quality presets) |
| Chat persistence | ✅ | ✅ | ⚠️ | ⚠️ | varies | ✅ (DB-backed, searchable) |
| Whiteboard | ✅ | ✅ | ✅ | ❌ | varies | ✅ (800x600 canvas) |
| Emotes / reactions | ✅ | ✅ | ✅ | ❌ | varies | ✅ (9 solarpunk emotes) |
| Game room | ✅ (18 games) | ❌ | ❌ | ❌ | ❌ | ❌ |
| Recording | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ (local browser recording) |
| Megaphone broadcast | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ (room-wide audio) |
| Locked video bubbles | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ (private groups) |
| Noise suppression | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ (WebAudio filter chain) |

### 4. DEVELOPER & ENTERPRISE

| Feature | Roam | Gather | WorkAdventure | **Selva** |
|---------|:----:|:------:|:-------------:|:---------:|
| Open source | ❌ | ❌ | ✅ (AGPL) | ❌ (proprietary) |
| Self-hosting | ❌ | ❌ | ✅ | ✅ (K3s + ArgoCD) |
| API / SDK | ✅ (MCP) | ✅ | ✅ | ✅ **(Python SDK + CLI + OpenAPI)** |
| SSO (OIDC) | ✅ | ✅ | ⚠️ | ✅ **(Janua SSO, own IdP)** |
| SCIM provisioning | ✅ | ⚠️ | ✅ | ⚠️ (roadmap) |
| GitHub integration | ✅ (PR on map) | ❌ | ❌ | ✅ **(webhook dispatch, auto-PR)** |
| Calendar integration | ✅ | ✅ | ❌ | ✅ (Google + Microsoft) |
| Webhook ecosystem | ⚠️ | ❌ | ❌ | ✅ **(GitHub, CRM, billing, Enclii, infra)** |
| Multi-tenant RLS | ❌ | ❌ | ❌ | ✅ **(PostgreSQL RLS by org_id)** |

### 5. ECOSYSTEM INTEGRATION (Selva-Exclusive)

| Capability | Competitors | **Selva** |
|-----------|:----------:|:---------:|
| CRM integration | ❌ | ✅ **PhyndCRM — federated CRM with 6 providers** |
| Billing / Stripe | ❌ | ✅ **Dhanam — MXN + USD, checkout links** |
| Legal intelligence | ❌ | ✅ **Tezca — 30K+ Mexican laws** |
| Compliance automation | ❌ | ✅ **Karafiel — SAT/CFDI tax defense** |
| 3D design platform | ❌ | ✅ **Yantra4D — parametric OpenSCAD** |
| Fabrication quoting | ❌ | ✅ **Cotiza — digital fabrication pricing** |
| Manufacturing execution | ❌ | ✅ **PravaraMES — work orders** |
| Pricing intelligence | ❌ | ✅ **Forgesight — 500+ vendor pricing** |
| Referral program | ❌ | ✅ **Cross-product referrals + ambassador tiers** |
| **Total ecosystem services** | **0** | **14 integrated platforms** |

### 6. OBSERVABILITY & OPS (Selva-Exclusive)

| Feature | All Competitors | **Selva** |
|---------|:--------------:|:---------:|
| Real-time ops feed | ❌ | ✅ WebSocket event stream |
| Metrics dashboard | ❌ | ✅ Utilization, throughput, cost, errors |
| Task kanban board | ❌ | ✅ QUEUED / RUNNING / COMPLETED / FAILED |
| Agent performance tracking | ❌ | ✅ Completion rate, approval rate, duration |
| Approval audit trail | ❌ | ✅ JWT sub claim attribution |
| Infrastructure tools | ❌ | ✅ Exec, restart, scale, logs, health, secrets |

---

## Pricing Positioning

| Platform | Per-Seat/Month | What You Get |
|----------|:--------------:|-------------|
| SoWork | $6-15 | Virtual office presence |
| WorkAdventure | $0-5 | Open-source spatial office |
| Gather | $7+ | Pixel-art spatial office with free tier |
| Sococo | $13-25 | Floor plan presence for Zoom users |
| Kumospace | $16+ | Photorealistic spatial office |
| Roam | $19.50 | 9-product suite (chat, video, AI, events) |
| Teamflow | $0-30 | Minimal bubble presence |
| **Selva** | **$149-499** | **10 AI agents that code, email, deploy, file taxes, and generate revenue autonomously** |

Selva's pricing is 7-25x higher because it's not selling presence — it's selling an autonomous workforce that replaces headcount.

---

## Category Analysis

### Where Selva Wins (No Competitor Matches)

1. **Autonomous AI Workforce** — 10 specialized agents executing tasks without human intervention (bounded by playbooks)
2. **Revenue Loop Automation** — CRM → lead detection → email → checkout → payment. Autonomous monetization.
3. **14-Platform Ecosystem** — Not just a virtual office but an entire business operating system
4. **Permission Engine** — Bounded autonomous execution with action allowlists, token budgets, financial caps
5. **Full-Stack DevOps** — Agents push code, create PRs, deploy, scale infrastructure

### Where Competitors Win (Selva's Gaps)

1. **Human-to-Human Presence** — Roam/Gather excel at making remote teams feel together. Selva's humans are supervisors, not collaborators.
2. **Video Quality** — Roam is enterprise-grade. Selva uses simple-peer (functional but not polished).
3. **Game Room** — Roam has 18 games. Selva is for work.
4. **Pricing Accessibility** — Gather is free. Selva requires meaningful investment.
5. **Native Mobile App** — Roam/Gather have iOS/Android. Selva is PWA-only.
6. **Enterprise Admin** — Roam has mature SCIM, analytics, admin controls.

### Where Selva Is Categorically Different

Selva doesn't compete with Gather for pixel art. It competes with:
- **GitHub Copilot Workspace** — AI development
- **CrewAI / LangGraph** — multi-agent orchestration
- **Salesforce Einstein** — autonomous CRM
- **ServiceNow AI Agents** — autonomous IT operations

The virtual office is the control plane. The product is autonomous operations.

---

## Roadmap: Closing Gaps

| Gap | Priority | Plan |
|-----|----------|------|
| 3D Voxel View | Phase 1 | React Three Fiber + MagicaVoxel (`ROADMAP_3D_VOXEL.md`) |
| Native Mobile | Phase 2 | React Native wrapper |
| Video Quality | Phase 2 | LiveKit SFU (staged) |
| SCIM | Phase 3 | Janua SCIM endpoints |
| Game Room | Low | Not core to AI workforce |

---

*Selva — not a virtual office that has AI. An AI workforce that has a virtual office.*
