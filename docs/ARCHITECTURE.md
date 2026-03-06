# Architecture Overview

AutoSwarm Office is a gamified multi-agent business orchestration platform built as a
polyglot monorepo with TypeScript frontend services and Python backend services.

## Component Diagram

```
                         +-------------------+
                         |    Office UI      |
                         |  (Next.js/Phaser) |
                         |    :4301          |
                         +--------+----------+
                                  |
                    +-------------+-------------+
                    |                           |
           REST + WebSocket              Colyseus WS
                    |                           |
           +--------v----------+     +----------v--------+
           |    Nexus API      |     |   Colyseus Server  |
           |   (FastAPI)       |     |    (Node.js)       |
           |    :4300          |     |     :4303          |
           +--------+----------+     +-------------------+
                    |
         +----------+----------+
         |                     |
   +-----v------+       +-----v------+
   |  PostgreSQL |       |   Redis    |
   |    :5432    |       |   :6379    |
   +-------------+       +-----+------+
                               |
                         +-----v------+
                         |  Workers   |
                         | (LangGraph)|
                         +-----+------+
                               |
                         +-----v------+
                         |  Gateway   |
                         | (OpenClaw) |
                         +------------+
```

### Service Responsibilities

| Service | Technology | Purpose |
|---------|-----------|---------|
| **Office UI** | Next.js 14, Phaser 3, React | Spatial 2D office environment, agent dashboards, approval modals |
| **Nexus API** | FastAPI, SQLAlchemy, Pydantic | Central REST API, WebSocket hub, auth middleware, task dispatch |
| **Colyseus** | Colyseus (Node.js) | Real-time game state synchronization for the spatial office |
| **Workers** | LangGraph, Python | Execute agent tasks in isolated environments with HITL interrupts |
| **Gateway** | OpenClaw (Node.js) | Persistent daemon for scheduled heartbeats and memory management |
| **PostgreSQL** | PostgreSQL 16 | Persistent storage for agents, departments, tasks, approvals, ledger |
| **Redis** | Redis 7 | Task queue (`autoswarm:tasks`), pub/sub for real-time events, caching |

## Data Flow

The primary interaction loop follows this path:

```
User Input (Gamepad)
    |
    v
Phaser Game Loop (Office UI)
    |
    v
Colyseus Room (state sync to all connected clients)
    |
    v
Nexus API (REST endpoint or WebSocket message)
    |
    v
Redis Task Queue (LPUSH to autoswarm:tasks)
    |
    v
Worker Process (BRPOP from queue)
    |
    v
LangGraph Execution (agent graph with tool nodes)
    |
    v
Tool Execution (file write, git commit, email send, etc.)
    |
    v
Permission Check (evaluate action against permission matrix)
    |
    +-- ALLOW --> Execute immediately, report result
    |
    +-- ASK ----> LangGraph interrupt() pauses execution
                      |
                      v
                  Nexus API creates ApprovalRequest row
                      |
                      v
                  WebSocket broadcasts {type: "approval_request"} to Office UI
                      |
                      v
                  Alert icon appears on agent avatar in Phaser
                      |
                      v
                  Tactician walks to agent, presses A (approve) or B (deny)
                      |
                      v
                  POST /api/v1/approvals/{id}/approve or /deny
                      |
                      v
                  Worker resumes (approved) or aborts (denied)
```

## Technology Rationale

| Choice | Rationale |
|--------|-----------|
| **Phaser 3** | MIT-licensed 2D game engine with mature tilemap support and gamepad API integration |
| **Colyseus** | MIT-licensed WebSocket framework designed for real-time multiplayer state sync |
| **FastAPI** | High-performance async Python framework with automatic OpenAPI docs and Pydantic validation |
| **LangGraph** | MIT-licensed framework for cyclic multi-agent workflows with native interrupt() support |
| **SQLAlchemy** | Industry-standard Python ORM with async support and strong typing |
| **Turborepo** | Monorepo build orchestration with intelligent caching for TypeScript packages |
| **UV** | Fast Python package manager with workspace support for Python packages |
| **pnpm** | Efficient Node.js package manager with workspace support and strict dependency management |

## Port Assignments

All ports are scoped to avoid conflicts with sibling MADFAM services
(Janua uses 4100-4104, Enclii uses 4200-4204).

| Port | Service | Protocol |
|------|---------|----------|
| 4300 | nexus-api | HTTP/WebSocket |
| 4301 | office-ui | HTTP |
| 4302 | admin dashboard | HTTP |
| 4303 | colyseus | WebSocket |
| 5432 | PostgreSQL | TCP |
| 6379 | Redis | TCP |

## Monorepo Structure

```
autoswarm-office/
  apps/
    nexus-api/        Python -- FastAPI central API
    office-ui/        TypeScript -- Next.js + Phaser spatial UI
      public/assets/  Generated pixel-art PNGs (sprites, tilesets, icons)
    colyseus/         TypeScript -- Colyseus game state server
    gateway/          TypeScript -- OpenClaw heartbeat daemon
    workers/          Python -- LangGraph task execution workers
  packages/
    shared-types/     TypeScript -- shared type definitions
    ui/               TypeScript -- shared React components (Button, AgentCard, ApprovalModal)
    config/           TypeScript -- ESLint and TSConfig presets
    orchestrator/     Python -- swarm orchestration, synergy, compute tokens
    permissions/      Python -- HITL permission matrix and engine
    inference/        Python -- LLM provider abstraction and routing
  scripts/
    generate-assets.js  Node.js sprite generator (@napi-rs/canvas)
  infra/
    docker/           Dockerfiles and Compose configs
    k8s/              Kubernetes manifests (base + production overlays)
```
