# Selva SDK Examples

## Setup

```bash
pip install selva-sdk
# or in dev:
uv sync
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SELVA_API_URL` | Nexus API base URL | `http://localhost:4300` |
| `SELVA_TOKEN` | Bearer auth token (from Janua) | — |

## Examples

### Basic Task Dispatch

```bash
python basic_dispatch.py
```

Dispatches a coding task and waits for it to complete.

### List Agents

```bash
python list_agents.py
```

Lists all registered agents with their roles and current status.

### Custom Workflow

```bash
python custom_workflow.py <workflow-id>
```

Dispatches a task using a custom workflow definition (created via the
Workflow Editor or API).
