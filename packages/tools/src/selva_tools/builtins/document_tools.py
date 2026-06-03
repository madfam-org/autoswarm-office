"""Document tools: PDF generation/parsing, markdown conversion, chart generation."""

from __future__ import annotations

import logging
import re
from typing import Any

from ..base import BaseTool, ToolResult

logger = logging.getLogger("selva.document_tools")


class GeneratePDFTool(BaseTool):
    name = "generate_pdf"
    description = (
        "Generate a PDF file from HTML content. Requires the weasyprint package to be installed."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "html_content": {
                    "type": "string",
                    "description": "HTML content to convert to PDF",
                },
                "output_path": {
                    "type": "string",
                    "description": "File path for the generated PDF",
                },
            },
            "required": ["html_content", "output_path"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        html_content = kwargs.get("html_content", "")
        output_path = kwargs.get("output_path", "")

        if not html_content:
            return ToolResult(success=False, error="html_content is empty")

        if not output_path:
            return ToolResult(success=False, error="output_path is required")

        try:
            import weasyprint

            doc = weasyprint.HTML(string=html_content)
            doc.write_pdf(output_path)

            from pathlib import Path

            size_bytes = Path(output_path).stat().st_size
            return ToolResult(
                output=f"PDF generated at {output_path} ({size_bytes} bytes)",
                data={"output_path": output_path, "size_bytes": size_bytes},
            )
        except ImportError:
            return ToolResult(
                success=False,
                error="weasyprint not installed. Install with: pip install weasyprint",
            )
        except Exception as exc:
            logger.error("generate_pdf failed: %s", exc)
            return ToolResult(success=False, error=str(exc))


class ParsePDFTool(BaseTool):
    name = "parse_pdf"
    description = (
        "Extract text content from a PDF file. Requires the pdfplumber package to be installed."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pdf_path": {
                    "type": "string",
                    "description": "Path to the PDF file",
                },
                "pages": {
                    "type": "string",
                    "description": "Page range (e.g. '1-5', '3', '1,3,5'). Omit for all pages.",
                    "default": "",
                },
            },
            "required": ["pdf_path"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        pdf_path = kwargs.get("pdf_path", "")
        pages_str = kwargs.get("pages", "")

        if not pdf_path:
            return ToolResult(success=False, error="pdf_path is required")

        try:
            import pdfplumber
        except ImportError:
            return ToolResult(
                success=False,
                error="pdfplumber not installed. Install with: pip install pdfplumber",
            )

        try:
            page_indices = _parse_page_range(pages_str) if pages_str else None

            extracted_text: list[str] = []
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)
                target_pages = page_indices if page_indices else range(total_pages)

                for idx in target_pages:
                    if idx < 0 or idx >= total_pages:
                        continue
                    page = pdf.pages[idx]
                    text = page.extract_text() or ""
                    if text:
                        extracted_text.append(f"--- Page {idx + 1} ---\n{text}")

            full_text = "\n\n".join(extracted_text)
            return ToolResult(
                output=full_text[:50000],  # Cap output
                data={
                    "total_pages": total_pages,
                    "extracted_pages": len(extracted_text),
                    "char_count": len(full_text),
                },
            )
        except Exception as exc:
            logger.error("parse_pdf failed: %s", exc)
            return ToolResult(success=False, error=str(exc))


def _parse_page_range(pages_str: str) -> list[int]:
    """Parse a page range string like '1-5', '3', '1,3,5' into zero-based indices."""
    indices: list[int] = []
    for part in pages_str.split(","):
        part = part.strip()
        if "-" in part:
            start_str, end_str = part.split("-", 1)
            start = int(start_str.strip()) - 1  # Convert to 0-based
            end = int(end_str.strip())  # inclusive, so no -1
            indices.extend(range(start, end))
        else:
            indices.append(int(part) - 1)  # Convert to 0-based
    return indices


class MarkdownToHTMLTool(BaseTool):
    name = "markdown_to_html"
    description = (
        "Convert Markdown text to HTML. "
        "Uses the markdown package if available, falls back to basic regex conversion."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "markdown": {
                    "type": "string",
                    "description": "Markdown text to convert",
                },
            },
            "required": ["markdown"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        md_text = kwargs.get("markdown", "")

        if not md_text:
            return ToolResult(success=False, error="markdown content is empty")

        try:
            import markdown

            html = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
        except ImportError:
            # Basic fallback conversion
            html = _basic_markdown_to_html(md_text)

        return ToolResult(
            output=html,
            data={"input_length": len(md_text), "output_length": len(html)},
        )


def _basic_markdown_to_html(text: str) -> str:
    """Basic markdown to HTML conversion using regex (fallback)."""
    # Headers
    text = re.sub(r"^### (.+)$", r"<h3>\1</h3>", text, flags=re.MULTILINE)
    text = re.sub(r"^## (.+)$", r"<h2>\1</h2>", text, flags=re.MULTILINE)
    text = re.sub(r"^# (.+)$", r"<h1>\1</h1>", text, flags=re.MULTILINE)
    # Bold and italic
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    # Code
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    # Links
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', text)
    # Line breaks
    text = re.sub(r"\n\n", "</p><p>", text)
    text = f"<p>{text}</p>"
    return text


class GenerateChartTool(BaseTool):
    name = "generate_chart"
    description = (
        "Generate a chart image (bar, line, or pie) from data. Requires matplotlib to be installed."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "chart_type": {
                    "type": "string",
                    "enum": ["bar", "line", "pie"],
                    "description": "Type of chart to generate",
                },
                "data": {
                    "type": "object",
                    "description": "Chart data with 'labels' (list) and 'values' (list) keys",
                    "properties": {
                        "labels": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "values": {
                            "type": "array",
                            "items": {"type": "number"},
                        },
                    },
                    "required": ["labels", "values"],
                },
                "title": {
                    "type": "string",
                    "description": "Chart title",
                    "default": "Chart",
                },
                "output_path": {
                    "type": "string",
                    "description": "Output file path (PNG or SVG)",
                },
            },
            "required": ["chart_type", "data", "output_path"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        chart_type = kwargs.get("chart_type", "bar")
        data = kwargs.get("data", {})
        title = kwargs.get("title", "Chart")
        output_path = kwargs.get("output_path", "")

        labels = data.get("labels", [])
        values = data.get("values", [])

        if not labels or not values:
            return ToolResult(success=False, error="data must contain 'labels' and 'values' lists")

        if len(labels) != len(values):
            return ToolResult(
                success=False,
                error=f"labels ({len(labels)}) and values ({len(values)}) must have same length",
            )

        if not output_path:
            return ToolResult(success=False, error="output_path is required")

        try:
            import matplotlib

            matplotlib.use("Agg")  # Non-interactive backend
            import matplotlib.pyplot as plt
        except ImportError:
            return ToolResult(
                success=False,
                error="matplotlib not installed. Install with: pip install matplotlib",
            )

        try:
            fig, ax = plt.subplots(figsize=(8, 5))

            if chart_type == "bar":
                ax.bar(labels, values)
            elif chart_type == "line":
                ax.plot(labels, values, marker="o")
            elif chart_type == "pie":
                ax.pie(values, labels=labels, autopct="%1.1f%%")
            else:
                plt.close(fig)
                return ToolResult(
                    success=False,
                    error=f"Unsupported chart_type: {chart_type}",
                )

            ax.set_title(title)
            if chart_type != "pie":
                ax.tick_params(axis="x", rotation=45)

            fig.tight_layout()
            fig.savefig(output_path, dpi=150)
            plt.close(fig)

            from pathlib import Path

            size_bytes = Path(output_path).stat().st_size
            return ToolResult(
                output=f"{chart_type} chart saved to {output_path} ({size_bytes} bytes)",
                data={
                    "output_path": output_path,
                    "chart_type": chart_type,
                    "size_bytes": size_bytes,
                },
            )
        except Exception as exc:
            logger.error("generate_chart failed: %s", exc)
            return ToolResult(success=False, error=str(exc))
