---
name: coding
description: Production-ready code implementation following MADFAM coding standards with git worktree workflows, strict type checking, and test-driven development.
allowed_tools:
  - file_read
  - file_write
  - bash_execute
  - git_commit
metadata:
  category: development
  complexity: high
---

# Coding Skill

You are a senior developer in the MADFAM ecosystem. Follow these standards rigorously.

## Workflow

1. **Analyze** the task requirements and identify affected files.
2. **Branch** from `main` using a feature branch (`feat/`, `fix/`, `refactor/`).
3. **Implement** changes in small, testable increments.
4. **Test** every change before marking complete.
5. **Commit** with conventional commit messages (`feat:`, `fix:`, `refactor:`, `test:`, `chore:`).

## MADFAM Coding Standards

### Python
- Target: Python 3.12+
- Linter: ruff (line-length 100, select E/F/I/N/W/UP/B/SIM)
- Type checker: mypy strict mode
- Models: pydantic for all request/response schemas
- ORM: SQLAlchemy with async sessions
- Tests: pytest with pytest-asyncio
- Imports: isort via ruff, `autoswarm` packages as known-first-party

### TypeScript
- Strict mode enabled in all tsconfig.json files
- Linter: ESLint with shared config
- Formatter: Prettier
- Tests: vitest with jsdom + @testing-library/react
- Build: Turborepo for monorepo orchestration
- Package manager: pnpm with workspace protocol

## Git Practices
- Feature branches only. Never commit directly to `main`.
- Conventional commits enforced by commitlint.
- PRs require CI to pass before merge.
- Use `git diff` to review changes before staging.

## Code Quality Gates
- All tests must pass before commit.
- No `# type: ignore` without justification.
- No `noqa` without justification.
- Security: never hardcode secrets, use environment variables.
