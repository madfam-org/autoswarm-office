"""Database tools: SQL query, write, and schema inspection."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from ..base import BaseTool, ToolResult

logger = logging.getLogger("selva.database_tools")

# Patterns that indicate a write/DDL statement
_WRITE_PATTERNS = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|MERGE)\b",
    re.IGNORECASE,
)


class SQLQueryTool(BaseTool):
    name = "sql_query"
    description = (
        "Execute a read-only SQL SELECT query against a PostgreSQL database. "
        "Only SELECT statements are allowed. "
        "Uses DATABASE_URL env var by default."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "SQL SELECT query to execute",
                },
                "database_url": {
                    "type": "string",
                    "description": "Database connection URL (defaults to DATABASE_URL env var)",
                    "default": "",
                },
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = kwargs.get("query", "").strip()
        database_url = kwargs.get("database_url", "") or os.environ.get("DATABASE_URL", "")

        if not query:
            return ToolResult(success=False, error="Query is empty")

        # Security: reject non-SELECT statements (check BEFORE database_url so
        # clearly invalid queries fail fast regardless of configuration)
        if _WRITE_PATTERNS.match(query):
            return ToolResult(
                success=False,
                error="Only SELECT queries are allowed. Use sql_write for modifications.",
            )

        # Also reject if first meaningful keyword is not SELECT/WITH/EXPLAIN
        first_keyword = query.split()[0].upper() if query.split() else ""
        if first_keyword not in ("SELECT", "WITH", "EXPLAIN", "SHOW"):
            return ToolResult(
                success=False,
                error=f"Only SELECT/WITH/EXPLAIN/SHOW queries are allowed, got: {first_keyword}",
            )

        if not database_url:
            return ToolResult(
                success=False,
                error="No database_url provided and DATABASE_URL not set",
            )

        try:
            from sqlalchemy import text
            from sqlalchemy.ext.asyncio import create_async_engine

            # Convert postgres:// to postgresql+asyncpg://
            conn_url = database_url
            if conn_url.startswith("postgres://"):
                conn_url = conn_url.replace("postgres://", "postgresql+asyncpg://", 1)
            elif conn_url.startswith("postgresql://"):
                conn_url = conn_url.replace("postgresql://", "postgresql+asyncpg://", 1)

            engine = create_async_engine(conn_url, pool_pre_ping=True)
            try:
                async with engine.connect() as conn:
                    result = await conn.execute(text(query))
                    columns = list(result.keys())
                    rows = [dict(zip(columns, row, strict=False)) for row in result.fetchall()]
            finally:
                await engine.dispose()

            output_lines = [f"Returned {len(rows)} row(s)"]
            for row in rows[:50]:  # Cap output at 50 rows
                output_lines.append(str(row))

            return ToolResult(
                output="\n".join(output_lines),
                data={"rows": rows[:100], "columns": columns, "row_count": len(rows)},
            )
        except ImportError:
            return ToolResult(
                success=False,
                error="sqlalchemy[asyncpg] not installed",
            )
        except Exception as exc:
            logger.error("sql_query failed: %s", exc)
            return ToolResult(success=False, error=str(exc))


class SQLWriteTool(BaseTool):
    name = "sql_write"
    description = (
        "Execute a write SQL statement (INSERT, UPDATE, DELETE) against a database. "
        "WARNING: This tool requires HITL approval before execution. "
        "Uses DATABASE_URL env var by default."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "SQL write statement (INSERT, UPDATE, DELETE)",
                },
                "database_url": {
                    "type": "string",
                    "description": "Database connection URL (defaults to DATABASE_URL env var)",
                    "default": "",
                },
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = kwargs.get("query", "").strip()
        database_url = kwargs.get("database_url", "") or os.environ.get("DATABASE_URL", "")

        if not query:
            return ToolResult(success=False, error="Query is empty")

        # Security: validate query type BEFORE checking database_url so clearly
        # invalid queries fail fast regardless of configuration
        first_keyword = query.split()[0].upper() if query.split() else ""
        if first_keyword in ("DROP", "TRUNCATE", "ALTER", "CREATE"):
            return ToolResult(
                success=False,
                error=f"DDL statements ({first_keyword}) are not allowed via sql_write",
            )

        if first_keyword not in ("INSERT", "UPDATE", "DELETE", "REPLACE", "MERGE"):
            return ToolResult(
                success=False,
                error=f"Only INSERT/UPDATE/DELETE allowed, got: {first_keyword}",
            )

        if not database_url:
            return ToolResult(
                success=False,
                error="No database_url provided and DATABASE_URL not set",
            )

        try:
            from sqlalchemy import text
            from sqlalchemy.ext.asyncio import create_async_engine

            conn_url = database_url
            if conn_url.startswith("postgres://"):
                conn_url = conn_url.replace("postgres://", "postgresql+asyncpg://", 1)
            elif conn_url.startswith("postgresql://"):
                conn_url = conn_url.replace("postgresql://", "postgresql+asyncpg://", 1)

            engine = create_async_engine(conn_url, pool_pre_ping=True)
            try:
                async with engine.begin() as conn:
                    result = await conn.execute(text(query))
                    affected = result.rowcount
            finally:
                await engine.dispose()

            return ToolResult(
                output=f"Query executed successfully. {affected} row(s) affected.",
                data={"affected_rows": affected, "query": query[:200]},
            )
        except ImportError:
            return ToolResult(
                success=False,
                error="sqlalchemy[asyncpg] not installed",
            )
        except Exception as exc:
            logger.error("sql_write failed: %s", exc)
            return ToolResult(success=False, error=str(exc))


class DatabaseSchemaTool(BaseTool):
    name = "database_schema"
    description = (
        "Inspect database schema: list tables and their columns. "
        "Uses DATABASE_URL env var by default."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "database_url": {
                    "type": "string",
                    "description": "Database connection URL (defaults to DATABASE_URL env var)",
                    "default": "",
                },
                "table_name": {
                    "type": "string",
                    "description": "Specific table to inspect (omit to list all tables)",
                    "default": "",
                },
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        database_url = kwargs.get("database_url", "") or os.environ.get("DATABASE_URL", "")
        table_name = kwargs.get("table_name", "")

        if not database_url:
            return ToolResult(
                success=False,
                error="No database_url provided and DATABASE_URL not set",
            )

        try:
            from sqlalchemy import inspect
            from sqlalchemy.ext.asyncio import create_async_engine

            conn_url = database_url
            if conn_url.startswith("postgres://"):
                conn_url = conn_url.replace("postgres://", "postgresql+asyncpg://", 1)
            elif conn_url.startswith("postgresql://"):
                conn_url = conn_url.replace("postgresql://", "postgresql+asyncpg://", 1)

            engine = create_async_engine(conn_url, pool_pre_ping=True)
            try:
                async with engine.connect() as conn:
                    if table_name:
                        columns = await conn.run_sync(
                            lambda sync_conn: inspect(sync_conn).get_columns(table_name)
                        )
                        col_info = [
                            {
                                "name": c["name"],
                                "type": str(c["type"]),
                                "nullable": c.get("nullable", True),
                            }
                            for c in columns
                        ]
                        output = f"Table '{table_name}': {len(col_info)} column(s)\n"
                        for c in col_info:
                            nullable = "NULL" if c["nullable"] else "NOT NULL"
                            output += f"  - {c['name']} ({c['type']}) {nullable}\n"
                        return ToolResult(
                            output=output.strip(),
                            data={"table": table_name, "columns": col_info},
                        )
                    else:
                        tables = await conn.run_sync(
                            lambda sync_conn: inspect(sync_conn).get_table_names()
                        )
                        output = f"Database has {len(tables)} table(s):\n"
                        output += "\n".join(f"  - {t}" for t in sorted(tables))
                        return ToolResult(
                            output=output,
                            data={"tables": sorted(tables), "count": len(tables)},
                        )
            finally:
                await engine.dispose()
        except ImportError:
            return ToolResult(
                success=False,
                error="sqlalchemy[asyncpg] not installed",
            )
        except Exception as exc:
            logger.error("database_schema failed: %s", exc)
            return ToolResult(success=False, error=str(exc))
