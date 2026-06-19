"""SKILL.md format: the Anthropic Agent Skills contract (validated + rendered).

Format (verified against Anthropic docs via deep research): YAML frontmatter with
two REQUIRED fields — ``name`` (<=64 chars, ``^[a-z0-9-]+$``, no XML tags, may not
contain 'anthropic'/'claude') and ``description`` (non-empty, <=1024 chars, no XML
tags). The description is the load-bearing triggering artifact: third person,
states WHAT the skill does AND WHEN to use it. Body kept lean (<500 lines);
Manthana provenance is written to a sidecar (provenance.py), not the frontmatter,
to keep SKILL.md portable across surfaces.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import re
from dataclasses import dataclass

NAME_MAX = 64
DESCRIPTION_MAX = 1024
BODY_MAX_LINES = 500
NAME_RE = re.compile(r"^[a-z0-9-]+$")
_RESERVED = ("anthropic", "claude")
_XML_TAG = re.compile(r"<[^>]+>")
_NON_SLUG = re.compile(r"[^a-z0-9]+")
# C0/C1 control chars (incl. NUL, BEL, VT, FF, CR) — break YAML or mutate silently.
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_FALLBACK_NAME = "mined-skill"


@dataclass
class SkillDraft:
    name: str
    description: str
    body: str


def validate_name(name: str) -> list[str]:
    errors: list[str] = []
    if not name:
        errors.append("name is required")
        return errors
    if len(name) > NAME_MAX:
        errors.append(f"name exceeds {NAME_MAX} chars")
    if not NAME_RE.match(name):
        errors.append("name must match ^[a-z0-9-]+$ (lowercase, digits, hyphens)")
    if any(word in name for word in _RESERVED):
        errors.append("name may not contain 'anthropic' or 'claude'")
    return errors


def validate_description(description: str) -> list[str]:
    errors: list[str] = []
    if not description or not description.strip():
        errors.append("description is required")
        return errors
    if len(description) > DESCRIPTION_MAX:
        errors.append(f"description exceeds {DESCRIPTION_MAX} chars")
    if _XML_TAG.search(description):
        errors.append("description may not contain XML tags")
    if _CONTROL.search(description):
        errors.append("description may not contain control characters")
    return errors


def validate_draft(draft: SkillDraft) -> list[str]:
    return [
        *validate_name(draft.name),
        *validate_description(draft.description),
        *([] if draft.body.strip() else ["body is required"]),
    ]


def slugify_name(text: str, fallback: str = _FALLBACK_NAME) -> str:
    """Coerce arbitrary text into a valid skill name (self-guaranteeing output)."""
    slug = _NON_SLUG.sub("-", text.lower()).strip("-")
    # Substring removal can re-form a reserved word (e.g. 'antclaudehropic' ->
    # 'anthropic'), so iterate to a fixpoint.
    while any(word in slug for word in _RESERVED):
        for word in _RESERVED:
            slug = slug.replace(word, "")
    slug = re.sub(r"-+", "-", slug).strip("-")[:NAME_MAX].strip("-")
    return slug or fallback


def repair_draft(draft: SkillDraft) -> SkillDraft:
    """Coerce a (possibly LLM-produced) draft toward validity: slug a bad name,
    strip XML tags + control chars, truncate an over-long description. The name is
    guaranteed valid (hard fallback if slugify still fails)."""
    name = draft.name if not validate_name(draft.name) else slugify_name(draft.name)
    if validate_name(name):  # belt: slugify output must be valid, else hard fallback
        name = _FALLBACK_NAME
    description = _CONTROL.sub("", _XML_TAG.sub("", draft.description)).strip()
    if len(description) > DESCRIPTION_MAX:
        description = description[: DESCRIPTION_MAX - 1].rstrip() + "…"
    return SkillDraft(name=name, description=description, body=draft.body)


def _yaml_double_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return f'"{escaped}"'


def render_skill_md(draft: SkillDraft) -> str:
    """Render a SKILL.md (YAML frontmatter + body). name is slug-safe (unquoted);
    description is a double-quoted YAML scalar."""
    body = draft.body.strip()
    return (
        "---\n"
        f"name: {draft.name}\n"
        f"description: {_yaml_double_quote(draft.description)}\n"
        "---\n\n"
        f"{body}\n"
    )


__all__ = [
    "SkillDraft",
    "validate_name",
    "validate_description",
    "validate_draft",
    "slugify_name",
    "repair_draft",
    "render_skill_md",
    "NAME_MAX",
    "DESCRIPTION_MAX",
    "BODY_MAX_LINES",
]
