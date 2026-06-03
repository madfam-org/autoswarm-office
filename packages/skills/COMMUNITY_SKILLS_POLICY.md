# Community Skills Policy

## Why Community Skills Are Excluded from Main Ruff Linting

Community skills are vendored from
[ComposioHQ/awesome-claude-skills](https://github.com/ComposioHQ/awesome-claude-skills) and
other third-party sources. They follow their own coding conventions that may not
align with Selva's strict `ruff` configuration (target py312, line-length
100, strict rule selection). Enforcing our project-level linting on externally
authored code would create two problems:

1. **Upstream drift** -- fixing lint errors in vendored files makes it harder to
   pull in upstream updates because every merge produces conflicts against our
   local reformats.
2. **False ownership** -- contributors would be forced to "own" style decisions
   in code they did not write, blurring accountability.

For these reasons the root `pyproject.toml` contains:

```toml
[tool.ruff]
extend-exclude = ["packages/skills/community-skills"]
```

A separate, non-blocking CI job (`lint-community-skills`) runs a reduced rule
set (`E` + `F` -- syntax errors and pyflakes only) on PRs that touch community
skill files. This catches genuine bugs without enforcing stylistic preferences.

## Acceptance Criteria for Community Skill Contributions

A community skill PR must satisfy all of the following before merge:

1. **Single-purpose script** -- the skill performs exactly one well-defined
   action (e.g., "generate invoice PDF", "fetch Slack GIF").
2. **YAML frontmatter** -- the script begins with a YAML header block containing
   at minimum `name`, `description`, and `author`.
3. **No external network calls at import time** -- network I/O must happen only
   when the skill is explicitly invoked.
4. **No filesystem writes outside of designated output directories** -- skills
   must not modify project source, configuration, or dependency files.
5. **Passes reduced lint** -- `uv run ruff check --select E,F <skill_dir>`
   exits 0 (no syntax errors, no undefined names).
6. **Includes a brief README or docstring** explaining usage, required
   environment variables, and expected input/output.

## Security Review Requirements

Every community skill undergoes a security review before being vendored:

| Check | Description |
|-------|-------------|
| **No secrets in source** | No hardcoded API keys, tokens, passwords, or credentials. |
| **No shell injection** | `subprocess` calls must use list form (`["cmd", "arg"]`), never `shell=True` with unsanitized input. |
| **No arbitrary code execution** | No `eval()`, `exec()`, or `compile()` on user-supplied data. |
| **Sandboxed I/O** | File operations are scoped; no writes to `/`, `~`, or project root. |
| **Dependency audit** | Any additional pip dependencies are documented and vetted for known CVEs. |
| **Network scope** | Outbound network calls are documented; no unexpected exfiltration vectors. |

Reviewers should run `uv run ruff check --select S <skill_dir>` (flake8-bandit
rules) as an additional advisory scan.

## How to Enable Community Skills at Runtime

Community skills are **disabled by default**. There are three ways to enable them:

### 1. Environment Variable

```bash
export SELVA_COMMUNITY_SKILLS_ENABLED=true
```

Set this before starting the application. The skill registry reads the variable
on startup.

### 2. Runtime API (Python)

```python
from selva_skills import get_skill_registry

registry = get_skill_registry()
registry.enable_community_skills()
```

### 3. REST API

```
POST /api/v1/skills/community/enable
Authorization: Bearer <token>
```

Requires an authenticated session with admin privileges.

### Precedence Rules

- Core skills (in `packages/skills/skill-definitions/`) are **always loaded**
  and take precedence on name collision with community skills.
- `SkillTier` (`CORE` | `COMMUNITY`) is assigned by the registry during
  discovery, not from YAML frontmatter.
- Disabling community skills at runtime unloads them from the active registry
  but does not delete files from disk.
