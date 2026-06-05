"""Data processing tools: JSON parse, CSV read, data transform."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from ..base import BaseTool, ToolResult
from ..safe_eval import safe_eval_expression


class JsonParseTool(BaseTool):
    name = "json_parse"
    description = "Parse a JSON string and optionally extract a value by JSONPath key"

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "json_string": {"type": "string", "description": "JSON string to parse"},
                "key": {
                    "type": "string",
                    "description": "Dot-separated key path (e.g. 'data.items.0.name')",
                    "default": "",
                },
            },
            "required": ["json_string"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        json_string = kwargs.get("json_string", "")
        key = kwargs.get("key", "")
        try:
            data = json.loads(json_string)
            if key:
                for part in key.split("."):
                    if isinstance(data, dict):
                        data = data[part]
                    elif isinstance(data, list):
                        data = data[int(part)]
            return ToolResult(
                output=json.dumps(data, indent=2) if not isinstance(data, str) else data,
                data={"parsed": data},
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


class CsvReadTool(BaseTool):
    name = "csv_read"
    description = "Read and parse CSV content from a string or file path"

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "CSV content string"},
                "path": {"type": "string", "description": "CSV file path (if no content)"},
                "max_rows": {"type": "integer", "default": 100},
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        content = kwargs.get("content", "")
        path = kwargs.get("path", "")
        max_rows = kwargs.get("max_rows", 100)

        try:
            if not content and path:
                from pathlib import Path

                content = Path(path).read_text(encoding="utf-8")
            if not content:
                return ToolResult(success=False, error="No CSV content or path provided")

            reader = csv.DictReader(io.StringIO(content))
            rows = []
            for i, row in enumerate(reader):
                if i >= max_rows:
                    break
                rows.append(dict(row))

            output = json.dumps(rows, indent=2)
            return ToolResult(output=output, data={"rows": rows, "count": len(rows)})
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


class DataTransformTool(BaseTool):
    name = "data_transform"
    description = "Apply a Python expression to transform data"

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "data": {"description": "Input data (JSON string or value)"},
                "expression": {
                    "type": "string",
                    "description": "Python expression using 'data' variable",
                },
            },
            "required": ["data", "expression"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        data = kwargs.get("data")
        expression = kwargs.get("expression", "")

        if isinstance(data, str):
            import contextlib

            with contextlib.suppress(json.JSONDecodeError):
                data = json.loads(data)

        try:
            sandbox_locals = {
                "data": data,
                "len": len,
                "sorted": sorted,
                "str": str,
                "int": int,
                "float": float,
            }
            result = safe_eval_expression(
                expression,
                sandbox_locals,
                allowed_call_targets={
                    "len",
                    "sorted",
                    "str",
                    "int",
                    "float",
                },
                allowed_get_attrs_for={"data"},
            )
            output = json.dumps(result, indent=2) if not isinstance(result, str) else result
            return ToolResult(output=output, data={"result": result})
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
