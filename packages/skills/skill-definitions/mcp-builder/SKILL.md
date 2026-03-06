---
name: mcp-builder
description: Model Context Protocol server development for building platform extensions and tool integrations.
allowed_tools:
  - file_read
  - file_write
  - bash_execute
metadata:
  category: development
  complexity: high
---

# MCP Builder Skill

You build Model Context Protocol (MCP) servers to extend the MADFAM platform.

## MCP Server Structure

An MCP server exposes tools, resources, and prompts to LLM agents:

```
my-mcp-server/
  src/
    index.ts          # Server entry point
    tools/            # Tool implementations
    resources/        # Resource providers
    prompts/          # Prompt templates
  package.json
  tsconfig.json
```

## Tool Development

Each tool must define:
- **name**: Unique identifier (kebab-case).
- **description**: Clear explanation of what the tool does.
- **inputSchema**: JSON Schema for parameters.
- **handler**: Async function implementing the tool logic.

## Best Practices

- Keep tools focused and single-purpose.
- Validate all inputs against the schema before processing.
- Return structured results (not just strings).
- Handle errors gracefully with descriptive messages.
- Log tool invocations for debugging.
- Rate-limit external API calls.

## Integration with AutoSwarm

MCP servers in MADFAM register via the nexus-api configuration.
Each agent can access MCP tools based on their skill permissions.
The permission engine evaluates tool calls through the standard HITL matrix.
