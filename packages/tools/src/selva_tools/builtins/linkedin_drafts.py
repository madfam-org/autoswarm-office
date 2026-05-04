"""LinkedIn DRAFT-ONLY generator. NO posting — drafts only, by design.

Why this is draft-only and how it differs from other social tools
=================================================================

LinkedIn has no automation-friendly promo-posting API. The Marketing API
requires partnership status that MADFAM does not (and likely will not)
hold, and the public REST API only permits posting via tokens granted to
the *signed-in human user*. There is no agent-runtime equivalent of
PRAW (Reddit), at-protocol (Bluesky), or the Mastodon HTTP API — every
"LinkedIn automation" SaaS in the wild operates either by reverse-
engineering the cookie session (ToS violation, account-ban risk) or by
holding a user's password (worse).

The pragmatic alternative is **drafts**: Selva agents generate
high-quality, channel-tuned post drafts and write them to artifact
storage. The operator reviews each one and copy-pastes into the
LinkedIn web composer manually. This sits cleanly alongside Reddit
(``reddit_post``), Mastodon (``mastodon_post``), and Bluesky
(``bluesky_post``) which all post directly — LinkedIn is the
deliberate exception.

Sibling tool ``linkedin_draft_list`` reads back recent drafts so the
operator can browse what's queued.

Hook + 1300-char tuning notes (informs caller defaults, not enforced)
---------------------------------------------------------------------

LinkedIn's feed truncates posts at the **"see more"** cutoff (~140
chars on mobile, ~210 chars on desktop). Anything past the cutoff is
hidden until a click. The first 140 chars therefore carry
disproportionate weight — the "hook". This module returns the hook as
a separate field on the result so the operator can copy it independently
to verify the in-feed preview before pasting the full body.

Long-form posts (1300-1500 chars) outperform short ones for B2B
audiences in LinkedIn's algorithmic feed (per multiple 2024-2025
analyses), but the hook is what gates whether anyone sees that
performance. Build hook first, body second.

DO NOT add an AI-generated disclosure footer to LinkedIn posts. The
LinkedIn algorithm penalizes such disclosures heavily (visible in
2025 organic-reach studies) and because the operator pastes manually,
the post is — under most platform-ToS readings — the operator's
own content. This is opposite to the Reddit policy (where disclosure
is mandatory because the post is automated end-to-end). The
distinction is the human-in-the-loop step.

Audience + ActionCategory
-------------------------

This tool is :class:`Audience.TENANT` — any tenant swarm can stage
LinkedIn drafts for their own org's social calendar. The action
category is ``MARKETING_SEND`` because drafting is a pre-staging
marketing-content action, identical in risk profile to drafting an
email or marketing push that a human will review before send.
We deliberately do NOT introduce a new permission category — that
would proliferate the matrix without adding signal.
"""

from __future__ import annotations

import datetime as _dt
import logging
import re
import uuid
from pathlib import Path
from typing import Any

from ..base import BaseTool, ToolResult
from ..storage import LocalFSStorage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_ALLOWED_AUDIENCES: frozenset[str] = frozenset(
    {
        "founders",
        "ctos",
        "accountants_mx",
        "developers",
        "b2b_buyers",
    }
)
"""Server-side allow-list mirrors the ``_AGENT_ROLE_ALLOWLIST`` pattern in
``email_tools.py``. The LLM picks one — it cannot invent a new audience.
Any other value raises ``ValueError`` before draft generation runs."""


_ALLOWED_PLATFORMS: frozenset[str] = frozenset(
    {
        "karafiel",
        "dhanam",
        "selva",
        "cotiza",
        "yantra4d",
        "phynecrm",
        "tezca",
        "fortuna",
        "rondelio",
        "sim4d",
        "routecraft",
        "forj",
        "blueprint-harvester",
        "digifab-quoting",
        "bloom-scroll",
        "forgesight",
        "madfam",
    }
)
"""MADFAM ecosystem platform names. Keep in sync with the project graph
in ``project_madfam_ecosystem.md`` — when a new product launches, add it
here so agents can stage drafts for it. Unknown platforms reject."""


_ALLOWED_TONES: frozenset[str] = frozenset(
    {"professional", "thought-leader", "founder-story", "technical", "celebratory"}
)


# LinkedIn's mobile "see more" cutoff is ~140 chars. Anything past this is
# hidden until the reader clicks. The first 140 chars are therefore the
# only content the algorithm has to decide whether to show your post in
# someone's feed. We extract them as a separate field so the operator can
# verify the in-feed preview before pasting.
HOOK_CHAR_LIMIT = 140

# Hard cap on the full body. LinkedIn's actual limit is 3000; we honor
# that as the default and let callers raise it within reason.
DEFAULT_MAX_CHARS = 3000


# ---------------------------------------------------------------------------
# Storage — content-addressable artifact store, same backend as
# SaveArtifactTool.
# ---------------------------------------------------------------------------

_storage = LocalFSStorage()


def _today_str() -> str:
    """UTC date in YYYY-MM-DD form for the artifact subpath.

    UTC (not Mexico City) so two operators in different TZs don't see
    drafts split across two date folders for the same calendar day.
    """
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Hook extraction — picks the natural sentence boundary inside the first
# ~140 chars, falling back to a hard cut + ellipsis.
# ---------------------------------------------------------------------------


_SENTENCE_BOUNDARY_RE = re.compile(r"[.?!](?=\s|$)")


def extract_hook(body: str, limit: int = HOOK_CHAR_LIMIT) -> str:
    """Return the first ``limit``-char hook used as the LinkedIn feed preview.

    Algorithm:
    1. If a sentence-terminator (``.``, ``?``, ``!``) lands within
       ``limit`` chars (followed by whitespace or end-of-string), cut
       there — including the terminator. This is what most readers see
       as a clean preview.
    2. Otherwise hard-cut at ``limit - 3`` chars and append ``"..."`` so
       the total length is exactly ``limit``.
    3. If the body is already <= ``limit`` chars, return as-is.

    The returned string is what the operator should verify against the
    LinkedIn in-feed preview before pasting the full body.
    """
    body = body.strip()
    if len(body) <= limit:
        return body

    # Search for the LAST sentence boundary within the limit so we keep
    # as much hook as possible. Iterating matches in order gives us the
    # right answer because boundaries are monotonically increasing.
    last_boundary: int | None = None
    for match in _SENTENCE_BOUNDARY_RE.finditer(body):
        end = match.end()  # position AFTER the punctuation
        if end > limit:
            break
        last_boundary = end

    if last_boundary is not None and last_boundary > 0:
        return body[:last_boundary].strip()

    # Hard cut. Reserve 3 chars for the ellipsis so total length == limit.
    return body[: limit - 3].rstrip() + "..."


# ---------------------------------------------------------------------------
# Frontmatter rendering. We hand-roll the YAML rather than importing PyYAML
# because (a) the schema is fixed, (b) we want stable byte-for-byte output
# for content-addressable dedup in storage, and (c) we want exact control
# over the manual-paste instructions.
# ---------------------------------------------------------------------------


def _render_draft_markdown(
    *,
    draft_id: str,
    audience: str,
    platform: str,
    topic: str,
    body: str,
    hook: str,
    char_count: int,
    created_at: str,
) -> str:
    """Return the full markdown blob written to artifact storage.

    Schema (frontmatter + body + operator instructions) is documented in
    the README. Frontmatter is parseable as YAML for the
    ``linkedin_draft_list`` listing tool.
    """
    # Embed via an f-string carefully — topic can contain colons/quotes.
    # We single-quote the YAML scalar and escape internal single-quotes
    # by doubling them, which is YAML 1.2's quoted-scalar escape rule.
    def _yaml_safe_quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    return (
        "---\n"
        f"draft_id: {draft_id}\n"
        f"audience: {audience}\n"
        f"platform: {platform}\n"
        f"topic: {_yaml_safe_quote(topic)}\n"
        f"created_at: {created_at}\n"
        f"char_count: {char_count}\n"
        "status: draft\n"
        "---\n"
        f"{body}\n"
        "\n"
        "---\n"
        f"**HOOK** (first {HOOK_CHAR_LIMIT} chars, what shows above \"see more\"):\n"
        f"{hook}\n"
        "\n"
        "**TO POST**: copy-paste body above into linkedin.com/feed -> New Post.\n"
        "**DO NOT** add an \"AI generated\" disclosure -- LinkedIn algo penalizes "
        "such disclosures heavily, but you're posting manually so the responsibility "
        "is yours per platform ToS interpretation.\n"
    )


# ---------------------------------------------------------------------------
# Tool: linkedin_draft_create
# ---------------------------------------------------------------------------


class LinkedInDraftCreateTool(BaseTool):
    """Generate a LinkedIn post DRAFT and save it to artifact storage.

    Returns a draft_id, the artifact storage path, a 200-char preview,
    the exact char_count, and the 140-char hook (first chars that show
    above the "see more" fold on mobile).

    NO POSTING. The operator must copy-paste the saved draft body into
    linkedin.com/feed manually. This is by design — see the module
    docstring for the rationale. Any future PR that adds a
    ``linkedin_post`` tool to this package should be rejected.
    """

    name = "linkedin_draft_create"
    description = (
        "Generate a LinkedIn post DRAFT (no posting, manual operator paste). "
        "Saves the full draft to artifact storage with frontmatter; returns "
        "draft_id, draft_path, 200-char preview, char_count, and the "
        f"{HOOK_CHAR_LIMIT}-char hook (the bit that shows above LinkedIn's "
        "\"see more\" fold). The operator copies the body into "
        "linkedin.com/feed manually."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "audience": {
                    "type": "string",
                    "description": (
                        "Target audience archetype. Must be one of: "
                        + ", ".join(sorted(_ALLOWED_AUDIENCES))
                    ),
                    "enum": sorted(_ALLOWED_AUDIENCES),
                },
                "platform": {
                    "type": "string",
                    "description": (
                        "MADFAM ecosystem platform the post is about. Must be "
                        "one of: " + ", ".join(sorted(_ALLOWED_PLATFORMS))
                    ),
                    "enum": sorted(_ALLOWED_PLATFORMS),
                },
                "topic": {
                    "type": "string",
                    "description": (
                        "Short brief describing what the post should cover. "
                        "The full draft body should be passed via 'body' "
                        "(when the agent has already drafted) — when 'body' "
                        "is absent, this tool simply stores the topic as the "
                        "body and the agent should call again with the "
                        "expanded body."
                    ),
                    "maxLength": 1000,
                },
                "body": {
                    "type": "string",
                    "description": (
                        "Full draft body. When omitted, the topic is used as "
                        "the body (useful for stub-and-iterate workflows)."
                    ),
                    "default": "",
                },
                "tone": {
                    "type": "string",
                    "description": (
                        "Tone hint stored in frontmatter; informational only. "
                        "One of: " + ", ".join(sorted(_ALLOWED_TONES))
                    ),
                    "enum": sorted(_ALLOWED_TONES),
                    "default": "professional",
                },
                "max_chars": {
                    "type": "integer",
                    "description": (
                        "Soft cap on the body length. LinkedIn's hard limit "
                        f"is 3000 (default {DEFAULT_MAX_CHARS}). When the "
                        "body exceeds the cap the tool returns success=false."
                    ),
                    "default": DEFAULT_MAX_CHARS,
                    "minimum": 200,
                    "maximum": 3000,
                },
            },
            "required": ["audience", "platform", "topic"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        audience = (kwargs.get("audience") or "").strip()
        platform = (kwargs.get("platform") or "").strip()
        topic = (kwargs.get("topic") or "").strip()
        body = (kwargs.get("body") or "").strip()
        tone = (kwargs.get("tone") or "professional").strip()
        max_chars = int(kwargs.get("max_chars") or DEFAULT_MAX_CHARS)

        # ---- Validation (server-side allow-lists; never trust the LLM) ----
        if audience not in _ALLOWED_AUDIENCES:
            return ToolResult(
                success=False,
                error=(
                    f"audience='{audience}' not allowed. Must be one of: "
                    + ", ".join(sorted(_ALLOWED_AUDIENCES))
                ),
            )
        if platform not in _ALLOWED_PLATFORMS:
            return ToolResult(
                success=False,
                error=(
                    f"platform='{platform}' not allowed. Must be one of: "
                    + ", ".join(sorted(_ALLOWED_PLATFORMS))
                ),
            )
        if not topic:
            return ToolResult(success=False, error="topic is required")
        if tone not in _ALLOWED_TONES:
            return ToolResult(
                success=False,
                error=(
                    f"tone='{tone}' not allowed. Must be one of: "
                    + ", ".join(sorted(_ALLOWED_TONES))
                ),
            )
        if max_chars < 200 or max_chars > 3000:
            return ToolResult(
                success=False,
                error="max_chars must be between 200 and 3000",
            )

        # If no explicit body was supplied, use the topic as the body so
        # downstream ``preview`` and ``hook`` extraction are still
        # well-defined. This supports stub-and-iterate workflows where
        # an agent stages a placeholder, then revisits with the full
        # body once research is complete.
        effective_body = body or topic

        if len(effective_body) > max_chars:
            return ToolResult(
                success=False,
                error=(
                    f"body length {len(effective_body)} exceeds max_chars={max_chars}; "
                    "trim before staging the draft"
                ),
            )

        char_count = len(effective_body)
        hook = extract_hook(effective_body, HOOK_CHAR_LIMIT)
        preview = effective_body[:200]

        # uuid4 — globally unique, no metadata leakage about ordering or
        # timing. Prepend the date in the storage path for human browsing.
        draft_id = str(uuid.uuid4())
        date = _today_str()
        created_at = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")

        markdown = _render_draft_markdown(
            draft_id=draft_id,
            audience=audience,
            platform=platform,
            topic=topic,
            body=effective_body,
            hook=hook,
            char_count=char_count,
            created_at=created_at,
        )

        # The artifact storage layer is content-addressable (SHA-256 of
        # the markdown blob). The "logical path" for browsing is
        # ``linkedin_drafts/<date>/<draft_id>.md`` — we surface that as
        # ``draft_path`` in the result and ALSO write a small index file
        # at that path pointing at the content-addressable artifact, so
        # ``linkedin_draft_list`` can find recent drafts without
        # re-hashing every artifact in the store.
        storage_path = await _save_draft_artifact(
            markdown=markdown,
            date=date,
            draft_id=draft_id,
        )

        logger.info(
            "linkedin_draft.created draft_id=%s audience=%s platform=%s chars=%d hook_chars=%d",
            draft_id,
            audience,
            platform,
            char_count,
            len(hook),
        )

        return ToolResult(
            success=True,
            output=(
                f"LinkedIn draft saved (id={draft_id}, {char_count} chars). "
                "Copy-paste the body into linkedin.com/feed manually."
            ),
            data={
                "draft_id": draft_id,
                "draft_path": storage_path,
                "preview": preview,
                "char_count": char_count,
                "hook": hook,
                "audience": audience,
                "platform": platform,
                "tone": tone,
                "status": "draft",
                "created_at": created_at,
                "logical_path": f"linkedin_drafts/{date}/{draft_id}.md",
            },
        )


# ---------------------------------------------------------------------------
# Storage helpers — used by both linkedin_drafts and linkedin_draft_list.
# ---------------------------------------------------------------------------


def _drafts_index_dir() -> Path:
    """Return the directory that stores the per-draft index files.

    The artifact backend stores content-addressable blobs; we maintain
    a small index of human-friendly paths -> blob paths so that listing
    recent drafts is O(N drafts) rather than O(N artifacts in the
    whole content store).

    Located alongside the artifact base dir so backups grab both.
    """
    base = Path(_storage._base).parent / "linkedin_drafts_index"
    base.mkdir(parents=True, exist_ok=True)
    return base


async def _save_draft_artifact(*, markdown: str, date: str, draft_id: str) -> str:
    """Persist the draft markdown via the content-addressable artifact
    backend and write a sidecar index file. Returns the storage path of
    the artifact blob."""
    import hashlib

    # Same flow as SaveArtifactTool: hash the bytes, save under
    # <hash[0:2]>/<hash[2:4]>/<hash>. We don't reuse SaveArtifactTool
    # directly because we need both the storage path AND a sidecar
    # mapping back to the human-friendly name.
    content_bytes = markdown.encode("utf-8")
    content_hash = hashlib.sha256(content_bytes).hexdigest()
    storage_path = await _storage.save(content_bytes, content_hash)

    # Sidecar index: linkedin_drafts/<date>/<draft_id>.idx
    # Single line: storage_path. The list tool reads these to find recent
    # drafts. We use a minimal single-line format so corruption of one
    # index file can't poison listing of the others.
    index_dir = _drafts_index_dir() / date
    index_dir.mkdir(parents=True, exist_ok=True)
    index_path = index_dir / f"{draft_id}.idx"
    index_path.write_text(storage_path + "\n", encoding="utf-8")

    return storage_path


# ---------------------------------------------------------------------------
# Frontmatter parsing (small, hand-rolled — same single-source rationale
# as the writer above; we don't take a YAML dep just to read 6 fields).
# ---------------------------------------------------------------------------


_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_KEY_VAL_RE = re.compile(r"^(\w+):\s*(.*)$")


def _parse_draft_frontmatter(markdown: str) -> dict[str, str]:
    """Best-effort frontmatter parse. Returns ``{}`` on any parse error
    rather than raising — the listing tool prefers a partial result over
    a hard failure when one draft has a bad index."""
    match = _FRONTMATTER_RE.match(markdown)
    if not match:
        return {}
    out: dict[str, str] = {}
    for line in match.group(1).splitlines():
        kv = _KEY_VAL_RE.match(line.strip())
        if not kv:
            continue
        key, raw_val = kv.group(1), kv.group(2).strip()
        # Unquote single-quoted scalars, including doubled-single-quote
        # escapes per YAML 1.2.
        if raw_val.startswith("'") and raw_val.endswith("'") and len(raw_val) >= 2:
            raw_val = raw_val[1:-1].replace("''", "'")
        out[key] = raw_val
    return out


# This tool is TENANT audience: any tenant swarm can stage drafts for
# their own org's LinkedIn calendar. There is intentionally NO
# ``linkedin_post`` tool in this package — drafts only, by design. See the
# module docstring for why.
__all__ = [
    "LinkedInDraftCreateTool",
    "extract_hook",
    "HOOK_CHAR_LIMIT",
    "DEFAULT_MAX_CHARS",
    "_drafts_index_dir",
    "_parse_draft_frontmatter",
    "_storage",
]
