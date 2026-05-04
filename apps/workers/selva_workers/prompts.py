"""Repo-context-aware system prompts for coding graph nodes."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_CONTEXT_LINES = 50

MX_FORMATTING = (
    "\n\nConvenciones de formato para Mexico:\n"
    "- Fechas: DD/MM/AAAA (ejemplo: 15/04/2026)\n"
    "- Numeros: coma para miles, punto para decimales (ejemplo: $1,234,567.89 MXN)\n"
    "- Moneda: siempre incluya 'MXN' o '$' con el monto\n"
    "- RFC: formato XAXX010101000 (persona moral 12 chars, persona fisica 13 chars)\n"
)


def _read_repo_context(repo_path: str | None) -> dict[str, str]:
    """Read lightweight repo context: top-level listing and key files.

    Returns a dict with keys ``listing``, ``readme``, ``claude_md`` (any may
    be empty strings).
    """
    ctx: dict[str, str] = {"listing": "", "readme": "", "claude_md": ""}
    if not repo_path:
        return ctx

    root = Path(repo_path)
    if not root.is_dir():
        return ctx

    # Top-level listing
    try:
        entries = sorted(p.name for p in root.iterdir() if not p.name.startswith("."))
        ctx["listing"] = "\n".join(entries[:40])
    except OSError:
        pass

    # README excerpt
    for name in ("README.md", "README.rst", "README.txt", "README"):
        readme = root / name
        if readme.is_file():
            try:
                lines = readme.read_text(errors="replace").splitlines()[:_MAX_CONTEXT_LINES]
                ctx["readme"] = "\n".join(lines)
            except OSError:
                pass
            break

    # CLAUDE.md excerpt (project conventions)
    claude_md = root / "CLAUDE.md"
    if claude_md.is_file():
        try:
            lines = claude_md.read_text(errors="replace").splitlines()[:_MAX_CONTEXT_LINES]
            ctx["claude_md"] = "\n".join(lines)
        except OSError:
            pass

    return ctx


def _detect_language(repo_path: str | None) -> str:
    """Best-effort language detection from file extensions."""
    if not repo_path:
        return "unknown"
    root = Path(repo_path)
    if not root.is_dir():
        return "unknown"

    ext_counts: dict[str, int] = {}
    try:
        for p in root.rglob("*"):
            if p.is_file() and not any(part.startswith(".") for part in p.parts):
                ext = p.suffix.lower()
                if ext in (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".rb"):
                    ext_counts[ext] = ext_counts.get(ext, 0) + 1
    except OSError:
        pass

    if not ext_counts:
        return "unknown"

    ext_to_lang = {
        ".py": "Python",
        ".ts": "TypeScript",
        ".tsx": "TypeScript/React",
        ".js": "JavaScript",
        ".jsx": "JavaScript/React",
        ".go": "Go",
        ".rs": "Rust",
        ".java": "Java",
        ".rb": "Ruby",
    }
    top_ext = max(ext_counts, key=ext_counts.get)  # type: ignore[arg-type]
    return ext_to_lang.get(top_ext, "unknown")


async def build_experience_context(
    agent_id: str,
    agent_role: str,
    task_description: str,
) -> str:
    """Retrieve relevant past experiences and agent memories for prompt injection.

    Returns a formatted string of past approaches, or empty string on any error.
    Graceful degradation: empty ExperienceStore or embedding failures return "".
    """
    try:
        from selva_memory import ExperienceStore, get_embedding_provider, get_memory_manager

        from .config import get_settings

        settings = get_settings()
        sections: list[str] = []

        # Search similar past experiences (per-role)
        embedder = get_embedding_provider()
        exp_store = ExperienceStore(
            role=agent_role,
            embedding_provider=embedder,
            persist_dir=settings.memory_persist_dir,
        )

        similar = await exp_store.search_similar(task_description, top_k=3, min_score=0.3)
        if similar:
            lines: list[str] = []
            for rec in similar:
                if rec.score >= 0.8:
                    badge = "[SUCCESS]"
                elif rec.score >= 0.3:
                    badge = "[PARTIAL]"
                else:
                    badge = "[FAILED]"
                lines.append(f"- {badge} {rec.approach[:200]} → {rec.outcome[:150]}")
            sections.append("## Past Approaches for Similar Tasks\n" + "\n".join(lines))

        # Agent-specific memories
        mem_manager = get_memory_manager(persist_dir=settings.memory_persist_dir)
        agent_ctx = await mem_manager.get_relevant_context(agent_id, task_description, top_k=3)
        if agent_ctx:
            sections.append(agent_ctx)

        # High-confidence shortcuts
        shortcuts = await exp_store.get_shortcuts(task_description, threshold=0.85)
        if shortcuts:
            shortcut_lines = [f"- {s[:200]}" for s in shortcuts]
            sections.append("## Proven Approaches (High Confidence)\n" + "\n".join(shortcut_lines))

        return "\n\n".join(sections)

    except Exception:
        logger.debug("Failed to build experience context", exc_info=True)
        return ""


def build_plan_prompt(
    description: str,
    repo_path: str | None = None,
    skill_ctx: str = "",
    experience_ctx: str = "",
    locale: str = "en",
) -> str:
    """Build a system prompt for the plan() node with repo context."""
    ctx = _read_repo_context(repo_path)
    lang = _detect_language(repo_path)

    if locale == "es-MX":
        sections = [
            "Usted es un desarrollador senior creando un plan de implementacion.",
            "Descomponga la tarea en una lista ordenada de cambios concretos en archivos.",
            (
                "Devuelva un objeto JSON con las claves: 'description' (cadena de texto) "
                "y 'steps' (arreglo de cadenas de texto)."
            ),
        ]
        lang_label = "Lenguaje principal"
        listing_label = "Archivos de nivel superior del repositorio"
        readme_label = f"Extracto del README (primeras {_MAX_CONTEXT_LINES} lineas)"
        conventions_label = "Convenciones del proyecto (extracto de CLAUDE.md)"
    else:
        sections = [
            "You are a senior developer creating an implementation plan.",
            "Break the task into an ordered list of concrete file changes.",
            "Return a JSON object with keys: 'description' (string) "
            "and 'steps' (array of strings).",
        ]
        lang_label = "Primary language"
        listing_label = "Repository top-level files"
        readme_label = f"README excerpt (first {_MAX_CONTEXT_LINES} lines)"
        conventions_label = "Project conventions (CLAUDE.md excerpt)"

    if lang != "unknown":
        sections.append(f"{lang_label}: {lang}.")

    if ctx["listing"]:
        sections.append(f"{listing_label}:\n```\n{ctx['listing']}\n```")

    if ctx["readme"]:
        sections.append(f"{readme_label}:\n```\n{ctx['readme']}\n```")

    if ctx["claude_md"]:
        sections.append(f"{conventions_label}:\n```\n{ctx['claude_md']}\n```")

    base = "\n\n".join(sections)
    if locale == "es-MX":
        base += MX_FORMATTING
    parts: list[str] = []
    if skill_ctx:
        parts.append(skill_ctx)
    if experience_ctx:
        parts.append(experience_ctx)
    parts.append(base)
    return "\n\n".join(parts)


def build_implement_prompt(
    step: str,
    iteration: int,
    repo_path: str | None = None,
    worktree_path: str | None = None,
    skill_ctx: str = "",
    experience_ctx: str = "",
    locale: str = "en",
) -> str:
    """Build a system prompt for the implement() node with strict JSON instructions."""
    ctx = _read_repo_context(worktree_path or repo_path)

    if locale == "es-MX":
        sections = [
            "Usted es un desarrollador senior implementando cambios de codigo.",
            (
                "IMPORTANTE: Devuelva UNICAMENTE un objeto JSON con la clave 'files' "
                "que contenga un arreglo de objetos."
            ),
            (
                "Cada objeto debe tener 'path' (ruta relativa a la raiz del proyecto) "
                "y 'content' (texto completo del archivo)."
            ),
            'Ejemplo: {"files": [{"path": "src/main.py", "content": "# contenido completo..."}]}',
            "NO devuelva markdown, explicaciones ni nada que no sea el objeto JSON.",
        ]
        listing_label = "Archivos existentes del proyecto"
        conventions_label = "Convenciones del proyecto (extracto de CLAUDE.md)"
        style_note = (
            "Prefiera editar archivos existentes en lugar de crear nuevos. "
            "Siga el estilo y convenciones de codificacion existentes del proyecto."
        )
    else:
        sections = [
            "You are a senior developer implementing code changes.",
            "IMPORTANT: Return ONLY a JSON object with key 'files' containing an array of objects.",
            "Each object must have 'path' (relative to project root) "
            "and 'content' (full file text).",
            'Example: {"files": [{"path": "src/main.py", "content": "# full file content..."}]}',
            "Do NOT return markdown, explanations, or anything other than the JSON object.",
        ]
        listing_label = "Existing project files"
        conventions_label = "Project conventions (CLAUDE.md excerpt)"
        style_note = (
            "Prefer editing existing files over creating new ones. "
            "Match the project's existing coding style and conventions."
        )

    if ctx["listing"]:
        sections.append(f"{listing_label}:\n```\n{ctx['listing']}\n```")

    if ctx["claude_md"]:
        sections.append(f"{conventions_label}:\n```\n{ctx['claude_md']}\n```")

    sections.append(style_note)

    base = "\n\n".join(sections)
    if locale == "es-MX":
        base += MX_FORMATTING
    parts_impl: list[str] = []
    if skill_ctx:
        parts_impl.append(skill_ctx)
    if experience_ctx:
        parts_impl.append(experience_ctx)
    parts_impl.append(base)
    return "\n\n".join(parts_impl)


def build_review_prompt(
    changes: str,
    skill_ctx: str = "",
    experience_ctx: str = "",
    locale: str = "en",
) -> str:
    """Build a system prompt for the review() node with enhanced criteria."""
    if locale == "es-MX":
        sections = [
            "Usted es un revisor minucioso de codigo. Evalue los cambios en cuanto a:",
            "1. Correccion -- el codigo hace lo que la tarea requiere?",
            "2. Seguridad -- traversal de rutas, inyeccion, exposicion de credenciales?",
            "3. Estilo -- coincide con las convenciones del proyecto y los modismos del lenguaje?",
            "4. Completitud -- se modificaron todos los archivos requeridos? Faltan importaciones?",
            "",
            (
                "Devuelva JSON con las claves: 'changes_reviewed' (int), 'issues_found' (int), "
                "'recommendation' ('approve' o 'revise'), 'issues' (arreglo de cadenas, opcional)."
            ),
        ]
    else:
        sections = [
            "You are a thorough code reviewer. Evaluate the changes for:",
            "1. Correctness — does the code do what the task requires?",
            "2. Security — path traversal, injection, credential exposure?",
            "3. Style — matches project conventions and language idioms?",
            "4. Completeness — are all required files modified? Any missing imports?",
            "",
            "Return JSON with keys: 'changes_reviewed' (int), 'issues_found' (int), "
            "'recommendation' ('approve' or 'revise'), 'issues' (array of strings, optional).",
        ]

    base = "\n".join(sections)
    if locale == "es-MX":
        base += MX_FORMATTING
    parts_rev: list[str] = []
    if skill_ctx:
        parts_rev.append(skill_ctx)
    if experience_ctx:
        parts_rev.append(experience_ctx)
    parts_rev.append(base)
    return "\n\n".join(parts_rev)
