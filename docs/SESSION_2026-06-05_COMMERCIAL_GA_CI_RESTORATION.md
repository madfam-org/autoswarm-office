# Session log - Commercial GA CI restoration (2026-06-05)

> **Scope:** resume after lost connection, reconcile local `main` with
> `origin/main`, restore the failed Commercial GA CI gates from the
> 2026-06-04 push, and leave a clean local handoff.
>
> **Failure source:** commit `f0447fe` (`chore: advance commercial ga readiness`)
> on 2026-06-04.
>
> **Local fix commit:** `d46ba32` (`fix: restore commercial ga ci gates`).

## Starting state

- Local `main` was clean and two commits behind `origin/main`.
- The two remote commits were digest-only deploy updates:
  - `8a2beb2` - staging digest update to `f0447fe`
  - `d1590fc` - production digest update
- Local `main` was fast-forwarded to `d1590fc`.
- Latest deploy/promotion workflows were green, but the `f0447fe` push had
  failed checks:
  - `CI` run `26983264816`
  - `Schema Drift` run `26983264824`

No production, tenant, customer, or shared-data operation was performed.

## Failed gates and root causes

| Gate | Symptom | Root cause | Fix |
|---|---|---|---|
| Schema Drift | `packages/shared-types/src/generated/api.ts` changed after generation | FastAPI route docstring changed but generated wire types were not committed | Ran `corepack pnpm generate-types` and committed generated API output |
| Ruff | 20 Python lint errors | Long lines/import order around tenant-identity validation, safe-eval, workflow edges, and Python runner files | Applied Ruff auto-fixes plus scoped manual wrapping |
| Python tests unlocked by lint fix | `python_runner_node` crashed with `_collect_declared_names(tree=...)` | Caller used a stale keyword name; helper accepts the AST module positional arg | Changed call to `_collect_declared_names(tree)` and narrowed helper type to `ast.Module` |
| Workflow unsafe-code test | Error contract changed to outer attribute-call denial | Safe-eval rejected `.system(...)`-style attribute calls before inspecting the nested forbidden `__import__` call | Validate attribute receiver first, then reject non-`.get()` attribute calls |
| Tools safe-eval test | Expected comprehension/f-string denial message no longer matched | Error text changed during safe-eval hardening | Restored the expected public error text |
| Trivy security scan | HIGH findings in `pnpm-lock.yaml` | Vulnerable transitive versions: `fast-uri@3.1.0`, `picomatch@4.0.3`, and old `picomatch@2.3.1` line | Added pnpm overrides and regenerated lockfile to resolve `fast-uri@3.1.2`, `picomatch@4.0.4`, and `picomatch@2.3.2` |

## Files touched

| Area | Files |
|---|---|
| Tenant-identity lint formatting | `apps/nexus-api/nexus_api/routers/tenant_identities.py`, `apps/nexus-api/tests/test_tenant_identities_router.py` |
| Generated wire types | `packages/shared-types/src/generated/api.ts` |
| Dependency security | `package.json`, `pnpm-lock.yaml` |
| Tools safe-eval lint/test contract | `packages/tools/src/selva_tools/safe_eval.py`, plus import-order lint in tools modules |
| Workflow safe-eval and runner | `packages/workflows/src/selva_workflows/safe_eval.py`, `packages/workflows/src/selva_workflows/nodes/python_runner.py`, `packages/workflows/src/selva_workflows/edges.py`, `packages/workflows/tests/test_compiler.py` |

## Verification run locally

| Command | Result |
|---|---|
| `uv run ruff check .` | OK |
| `corepack pnpm generate-types` | OK - generated 177 paths and 176 schemas |
| `corepack pnpm install --frozen-lockfile --lockfile-only` | OK |
| `uv run pytest tests/unit -q` | OK - 10 passed |
| `uv run pytest apps/nexus-api/tests/test_tenant_identities_router.py packages/tools/tests/test_safe_eval.py` | OK - 15 passed |
| `uv run pytest packages/workflows/tests/test_safe_eval.py packages/workflows/tests/test_compiler.py` | OK - 13 passed |
| `uv run mypy apps/nexus-api/nexus_api/routers/tenant_identities.py` | OK |
| `uv run mypy packages/workflows/src packages/tools/src` | OK - 129 source files |
| `corepack pnpm lint` | OK with existing warnings only |
| `corepack pnpm typecheck` | OK |
| `git diff --check` | OK |

## Local limits

- `trivy` is not installed locally, so the security scan was verified by
  lockfile resolution:
  - no resolved `fast-uri@3.1.0`
  - no resolved `picomatch@4.0.3`
  - no resolved `picomatch@2.3.1`
  - patched resolved versions are `fast-uri@3.1.2`, `picomatch@4.0.4`,
    and `picomatch@2.3.2`
- The Commercial GA regression command can only fully pass in CI or another
  environment with Postgres + pgvector:

  ```bash
  uv run pytest \
    packages/inference/tests/test_router.py \
    packages/inference/tests/test_router_budget_gate.py \
    packages/memory/tests/test_memory.py \
    apps/workers/tests/test_campaign_graph.py \
    apps/nexus-api/tests/test_routers.py::TestCreateApproval::test_approval_response_includes_agent_name \
    -q
  ```

  Locally, inference, worker, and approval portions passed, but
  `packages/memory/tests/test_memory.py` failed because no local Postgres was
  listening on `localhost:5432`.
- SQLite cannot substitute for the memory regression because
  `selva_memory.store` emits pgvector's `<=>` operator.

## Expected CI behavior after push

After the local fix commit is pushed to `origin/main`, these previously failed
gates should be re-run by GitHub Actions:

- `Schema Drift`: should pass because generated API types are committed.
- `Lint Python`: should pass because Ruff is green locally.
- `Security Scan`: should pass if Trivy only reports the previously observed
  `fast-uri` and `picomatch` lockfile CVEs.
- `Test Python`: should now run instead of being skipped after lint, and CI has
  the Postgres/pgvector service required by memory tests.

## Remaining operator action

Push is intentionally not performed by this session because it is a GitHub
write. To complete the remote wrap-up:

```bash
git push origin main
```

Then monitor `CI`, `Schema Drift`, `Deploy to Staging`, and `Build & Deploy`
for the new head SHA.
