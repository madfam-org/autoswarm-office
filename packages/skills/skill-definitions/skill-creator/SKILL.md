---
name: skill-creator
description: Meta-skill for creating new MADFAM skills following the AgentSkills specification with proper directory structure and validation.
allowed_tools:
  - file_read
  - file_write
metadata:
  category: meta
  complexity: low
---

# Skill Creator

You create new skills for the MADFAM platform following the AgentSkills specification.

## AgentSkills Directory Structure

```
skill-name/
  SKILL.md              # Required: YAML frontmatter + markdown instructions
  scripts/              # Optional: automation scripts
  references/           # Optional: reference documents
  assets/               # Optional: images, templates, etc.
```

## SKILL.md Format

```markdown
---
name: skill-name          # Must match directory name, kebab-case
description: Brief description of the skill (max 1024 chars)
license: MIT              # Optional
compatibility: ">=0.1.0"  # Optional
allowed_tools:            # Tools this skill grants access to
  - file_read
  - api_call
metadata:                 # Optional key-value pairs
  category: development
  complexity: medium
---

# Skill Title

Instructions for the agent when this skill is activated.
Keep under 5000 tokens for context efficiency.
```

## Naming Rules

- Use kebab-case: `my-skill-name`
- Lowercase alphanumeric and hyphens only
- Must match the parent directory name exactly
- Maximum 64 characters

## Validation Checklist

1. Directory name matches `name` field in frontmatter.
2. YAML frontmatter parses without errors.
3. `description` is under 1024 characters.
4. `allowed_tools` lists only valid ActionCategory values.
5. Instructions are under 5000 tokens.
6. Skill is registered in `DEFAULT_ROLE_SKILLS` if it's a default for a role.
