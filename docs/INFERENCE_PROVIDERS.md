# Inference Providers

Reference for LLM inference providers integrated into Selva, their pricing,
model catalogs, and routing configuration.

*Last updated: 2026-03-14*

## Provider Overview

| Provider | Type | API Format | Default Model | Vision Support |
|----------|------|------------|---------------|----------------|
| Anthropic | Proprietary | Anthropic Messages | claude-sonnet-4-20250514 | Yes |
| OpenAI | Proprietary | OpenAI Chat | gpt-4o | Yes |
| Groq | Open-source host | OpenAI-compat | llama-3.3-70b-versatile | No |
| Mistral | Proprietary | OpenAI-compat | mistral-large-latest | Yes |
| SiliconFlow | Open-source host | OpenAI-compat | THUDM/GLM-5 | Yes (GLM-4.5V) |
| Moonshot | Open-source host | OpenAI-compat | kimi-k2.5 | No |
| Together AI | Open-source host | OpenAI-compat | Llama-3.3-70B-Instruct | Qwen3-VL |
| Fireworks AI | Open-source host | OpenAI-compat | Llama-3.1-70B-Instruct | Qwen2.5-VL, Llama 4 Vision |
| DeepInfra | Open-source host | OpenAI-compat | Llama-3.3-70B-Instruct | Llama 3.2 Vision, Qwen3-VL |
| OpenRouter | Aggregator | OpenAI-compat | claude-sonnet-4 | Varies by model |
| Ollama | Local | Ollama REST | llama3.2 | Yes (local models) |

## Pricing (per million tokens, Llama 70B class)

| Provider | Input $/M | Output $/M | Notes |
|----------|-----------|------------|-------|
| Groq | $0.05 | $0.08 | Fastest inference, LPU hardware |
| DeepInfra | $0.23 | $0.40 | Cheapest per-token for 70B |
| Fireworks AI | $0.20 | $0.90 | Cheapest input, higher output (tiered) |
| Together AI | $0.54 | $0.54 | Flat rate, broadest catalog |
| Mistral | ~$2.00 | ~$6.00 | Mistral Large pricing (proprietary) |
| OpenRouter | Varies | Varies | Aggregator markup over underlying provider |
| OpenAI | ~$2.50 | ~$10.00 | GPT-4o pricing (proprietary) |
| Anthropic | ~$3.00 | ~$15.00 | Claude Sonnet 4 pricing (proprietary) |

Pricing as of March 2026. Check provider dashboards for current rates.

## Model Catalog Breadth

| Provider | Available Models | Strengths |
|----------|-----------------|-----------|
| Together AI | 200+ | Broadest open-source catalog, fine-tuning support |
| Fireworks AI | 80+ | Fast inference, function calling, serverless GPUs |
| DeepInfra | 77 | Lowest cost, pay-per-token, no minimum |
| OpenRouter | 100+ | Unified access to multiple providers, fallback routing |
| Groq | 20+ | Fastest TTFT (sub-100ms), LPU inference engine |
| Mistral | 10+ | Strong multilingual, code, and reasoning models |

## Selection Rationale

All open-source providers implement the `/v1/chat/completions` endpoint, allowing
integration via `GenericOpenAIProvider` with zero new provider classes.

### Alternatives Considered

| Provider | Why Not Selected |
|----------|-----------------|
| Anyscale | Merged into Fireworks AI ecosystem |
| Replicate | Per-second billing model less predictable for batch workloads |
| Perplexity | Focused on search/RAG, not general inference |
| Modal | More of a compute platform than inference API |

## Routing Configuration

### Task-Type Routing (Highest Priority)

When a graph node declares a `task_type` (e.g. `planning`, `coding`, `review`),
the router checks `org_config.model_assignments` first. If a matching assignment
exists and its provider is registered, that provider is selected and
`policy.model_override` is set to the assigned model. Falls through to priority-list
routing when no assignment matches.

Supported task types: `planning`, `coding`, `fast_coding`, `review`, `research`,
`crm`, `support`, `vision`, `embedding`.

Configure assignments in `~/.selva/org-config.yaml` (template at
`data/org-config-template.yaml`).

### Cloud Priority (Internal sensitivity)

Quality-first ordering for internal/non-sensitive workloads:

```
anthropic > openai > groq > mistral > moonshot > siliconflow > fireworks > together > deepinfra > openrouter
```

### Cheapest Priority (Public sensitivity)

Cost-first ordering for public/non-sensitive workloads:

```
deepinfra > groq > together > siliconflow > fireworks > mistral > moonshot > openrouter > openai > anthropic
```

### Sensitivity Routing

| Sensitivity | Routing Behavior |
|-------------|-----------------|
| `restricted` / `confidential` | Ollama only (local). Fails if unavailable. |
| `internal` | Cloud priority order. Falls through on unavailability. |
| `public` | Cheapest priority order. Falls through on unavailability. |

### Vision Routing

When a request contains multimodal content (`has_media()` returns True), the router
filters candidates to providers where `supports_vision == True` before applying
priority ordering. Falls through to all candidates if no vision providers are
registered.

## Configuration

Set API keys in `.env` to enable each provider:

```bash
# Proprietary
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# Open-source / cloud (any combination)
GROQ_API_KEY=gsk-...
MISTRAL_API_KEY=...
TOGETHER_API_KEY=...
FIREWORKS_API_KEY=...
DEEPINFRA_API_KEY=...
SILICONFLOW_API_KEY=...
MOONSHOT_API_KEY=...

# Aggregator
OPENROUTER_API_KEY=sk-or-...

# Local
OLLAMA_BASE_URL=http://localhost:11434

# Org config (task-type routing, custom providers)
ORG_CONFIG_PATH=~/.selva/org-config.yaml
```

Providers without API keys are silently skipped. The router selects from whatever
providers are registered. Additional providers can be defined in the org config.

### Provider Auth Patterns

| Provider | Auth Header | Key Format |
|----------|------------|------------|
| Anthropic | `x-api-key` | `sk-ant-...` |
| OpenAI | `Authorization: Bearer` | `sk-...` |
| Groq | `Authorization: Bearer` | `gsk_...` |
| Mistral | `Authorization: Bearer` | Plain string |
| Together | `Authorization: Bearer` | Plain string |
| Fireworks | `Authorization: Bearer` | `fw_...` |
| DeepInfra | `Authorization: Bearer` | Plain string |
| SiliconFlow | `Authorization: Bearer` | Plain string |
| Moonshot | `Authorization: Bearer` | Plain string |
| OpenRouter | `Authorization: Bearer` | `sk-or-...` |
| Ollama | None | Local, no auth |

### Intelligence Config API

The current org configuration is available via the nexus-api control plane:

```
GET /api/v1/intelligence/config
Authorization: Bearer <token>
```

Returns providers (without API keys), model assignments, priority lists, and
embedding config. Agent templates are excluded from the response.

## How to Add a New Provider

### Via org-config.yaml (dynamic, no code change)

Any OpenAI-compatible endpoint can be added at runtime:

```yaml
# ~/.selva/org-config.yaml
providers:
  my-provider:
    base_url: https://api.my-provider.com/v1
    api_key_env: MY_PROVIDER_API_KEY
    vision: false
    timeout: 120.0
```

Set the env var and restart the worker. The provider will be registered
automatically as a `GenericOpenAIProvider`.

### Via hardcoded registration (built-in)

For providers that should always be available:

1. Add the API key field to `apps/workers/selva_workers/config.py`:
   ```python
   my_provider_api_key: str | None = None
   ```

2. Register the provider in `packages/inference/madfam_inference/factory.py`
   inside `build_router_from_env()`:
   ```python
   if my_provider_api_key:
       providers["my-provider"] = GenericOpenAIProvider(
           base_url="https://api.my-provider.com/v1",
           api_key=my_provider_api_key,
           model="default-model",
           provider_name="my-provider",
       )
   ```

3. Add to priority lists in `packages/inference/madfam_inference/router.py`:
   ```python
   CLOUD_PRIORITY = [..., "my-provider", ...]
   CHEAPEST_PRIORITY = [..., "my-provider", ...]
   ```

4. Add env var to `.env.example` and update this document.

## Troubleshooting

### No providers configured warning

At startup the worker logs available providers. If you see:
```
WARNING: No cloud LLM API keys configured — only Ollama is available.
```
Set at least one cloud provider API key in `.env`.

### Verifying provider availability

The worker logs the full provider list at startup:
```
INFO: LLM providers available: anthropic, groq, ollama
```

You can also check via the API:
```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:4300/api/v1/intelligence/config
```

## Inference Proxy (Ecosystem Gateway)

Nexus-api exposes an **OpenAI-compatible proxy** at `/v1/` so ecosystem
services can centralise all LLM calls through Selva's `ModelRouter`.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/chat/completions` | Chat completion (streaming + non-streaming) |
| POST | `/v1/embeddings` | Text embeddings |

### Authentication

Bearer token via `WORKER_API_TOKEN`:
```bash
curl http://nexus-api:4300/v1/chat/completions \
  -H "Authorization: Bearer $WORKER_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"hello"}]}'
```

### Routing hints

Services can pass optional headers to influence routing:

| Header | Effect | Example |
|--------|--------|---------|
| `X-Task-Type` | Maps to `RoutingPolicy.task_type` (org-config model assignment) | `crm`, `coding`, `research` |
| `X-Sensitivity` | Maps to `RoutingPolicy.sensitivity` | `public`, `internal` |

When `model` is `"auto"`, the router picks the best provider via
task-type or priority-list routing. Otherwise the `model` value is
passed as `model_override` to the selected provider.

### Connected services

| Service | Config | Code changes |
|---------|--------|-------------|
| **PhyndCRM** | `OPENAI_BASE_URL=http://nexus-api.../v1` | None |
| **Fortuna** | `OPENAI_BASE_URL=http://nexus-api.../v1` | None |
| **Yantra4D** | `AI_BASE_URL=http://nexus-api.../v1`, `AI_PROVIDER=openai` | `ai_provider.py` passes `base_url` |

### Implementation

- Router: `apps/nexus-api/nexus_api/routers/inference_proxy.py`
- Factory: `packages/inference/madfam_inference/factory.py` (`build_router_from_env`)
- Both worker and proxy use the same factory to ensure identical routing

### Common API key format issues

| Provider | Common Mistake | Fix |
|----------|---------------|-----|
| Anthropic | Missing `sk-ant-` prefix | Copy full key from console.anthropic.com |
| Groq | Using wrong prefix | Key should start with `gsk_` |
| OpenRouter | Missing `sk-or-` prefix | Copy from openrouter.ai/keys |

### Provider timeout errors

Default git operation timeout is 120s. For large repos, increase via:
```bash
# In your org config
providers:
  my-provider:
    timeout: 300.0
```

## Top Models by Use Case

### Code Generation
| Model | Provider(s) | Notes |
|-------|-------------|-------|
| Claude Sonnet 4 | Anthropic, OpenRouter | Best code quality |
| Llama 3.3 70B Instruct | Together, DeepInfra, Groq | Best open-source for code |
| Mistral Large | Mistral | Strong code + reasoning |
| DeepSeek Coder V2 | Together, DeepInfra | Specialized for code |
| Qwen2.5-Coder-32B | Together, Fireworks | Strong coding, smaller footprint |

### Vision / Multimodal
| Model | Provider(s) | Notes |
|-------|-------------|-------|
| GPT-4o | OpenAI | Strongest general vision |
| Claude Sonnet 4 | Anthropic | Strong vision + reasoning |
| Mistral Large | Mistral | Vision-capable proprietary |
| Llama 3.2 90B Vision | DeepInfra | Best open-source vision |
| Qwen3-VL | Together, DeepInfra | Competitive open-source vision |
| Qwen2.5-VL | Fireworks | Fast inference, good quality |

### General Reasoning
| Model | Provider(s) | Notes |
|-------|-------------|-------|
| Claude Opus 4 | Anthropic | Highest capability |
| GPT-4o | OpenAI | Strong general purpose |
| Llama 3.3 70B | Together, DeepInfra, Fireworks, Groq | Best open-source general |
| Mixtral 8x22B | Together, Fireworks | Good quality/cost ratio |

### Fast / Cheap (Agent inner loops)
| Model | Provider(s) | Notes |
|-------|-------------|-------|
| Llama 3.3 70B | Groq | Fastest inference (sub-100ms TTFT) |
| Llama 3.1 8B | All OS providers | Sub-cent per call |
| Gemma 2 9B | Together, DeepInfra | Fast, good quality for size |
| Qwen2.5 7B | Together, Fireworks | Strong multilingual |
