"""v0 compaction prompt template.

A fixed template plus the session's normalized turns serialized as compact JSON;
the model is instructed to return a single ``EngineeringCompaction``-shaped JSON
object (decisions doc). Treated as a v0 prompt to refine after the first ~20 real
compactions. Turn content is bounded to keep the prompt size sane.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import json

from manthana.schemas import Session, Turn

PROMPT_VERSION = "v0"

_MAX_TURNS = 400
_MAX_CHARS = 600

_INSTRUCTIONS = """\
You are Manthana's compactor. Summarize ONE engineering session into a structured
digest. Read the turns (a JSON array of {seq, role, text, tool}) and return ONLY a
single JSON object — no prose, no code fences — with EXACTLY these keys:

  task_intent: string  (what the engineer set out to do)
  approach: string  (how they went about it, 1-3 sentences)
  artifacts: string[]  (concrete things produced)
  outcome: "success" | "partial" | "abandoned"
  reusable_pattern: boolean  (is there a generalizable pattern worth reusing?)
  friction_points: array of { "category": one of
      ["loop","tool_error","abandon","retry","deadend"], "description": string,
      "turn_refs": string[] }  (turn seq numbers as strings; [] if unknown)
  files_touched: string[]
  prs_opened: string[]
  tests_added: string[]
  dead_end_branches: string[]
  languages: string[]
  frameworks: string[]

Ground every field in the turns. Use [] for unknowns. Output JSON only.
"""


def _turn_repr(turn: Turn) -> dict[str, object]:
    text = turn.content or turn.tool_output or ""
    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS] + "…"
    item: dict[str, object] = {"seq": turn.seq, "role": str(turn.role), "text": text}
    if turn.tool_name:
        item["tool"] = turn.tool_name
    return item


def serialize_turns(turns: list[Turn]) -> str:
    sample = turns[:_MAX_TURNS]
    return json.dumps([_turn_repr(t) for t in sample], ensure_ascii=False)


def build_prompt(session: Session, turns: list[Turn]) -> str:
    header = (
        f"Session: project={session.project} surface={session.surface} "
        f"turns={session.turn_count}"
    )
    return f"{_INSTRUCTIONS}\n{header}\n\nTURNS:\n{serialize_turns(turns)}\n"


__all__ = ["build_prompt", "serialize_turns", "PROMPT_VERSION"]
