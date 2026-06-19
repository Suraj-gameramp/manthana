"""Skill miner tests — embeddings, clustering, SKILL.md format, synthesis,
provenance, and the end-to-end miner. Deterministic (HashingEmbedder + a mock /
no LLM), so no torch or model access is needed.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from manthana.agent.llm import MockProvider
from manthana.agent.skillminer import (
    HashingEmbedder,
    SkillMiner,
    cluster_compactions,
    community_detection,
    make_provenance,
    recurring,
    render_skill_md,
    validate_draft,
    write_proposal,
)
from manthana.agent.skillminer.embed import cosine
from manthana.agent.skillminer.skillmd import (
    SkillDraft,
    repair_draft,
    slugify_name,
    validate_description,
    validate_name,
)
from manthana.agent.skillminer.synthesize import fallback_draft, synthesize
from manthana.schemas import EngineeringCompaction, Outcome, Surface

_T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _comp(
    cid: str, session: str, actor: str, intent: str, approach: str = "do it"
) -> EngineeringCompaction:
    return EngineeringCompaction(
        id=cid,
        session_id=session,
        actor=actor,
        surface=Surface.claude_code,
        project="demo",
        started_at=_T0,
        ended_at=_T0,
        duration_seconds=1.0,
        task_intent=intent,
        approach=approach,
        outcome=Outcome.success,
    )


# ── embeddings ────────────────────────────────────────────────────────────
def test_hashing_embedder_similar_texts_cluster_together() -> None:
    e = HashingEmbedder()
    a, b, c = e.embed(
        ["fix flaky pytest timeout", "fix the flaky pytest timeout error", "design a logo in figma"]
    )
    assert cosine(a, b) > cosine(a, c)
    assert abs(sum(x * x for x in a) - 1.0) < 1e-6  # L2-normalized


# ── clustering ────────────────────────────────────────────────────────────
def test_community_detection_groups_and_separates() -> None:
    e = HashingEmbedder()
    vecs = e.embed(
        [
            "fix flaky pytest timeout",
            "fix flaky pytest timeout again",
            "fix flaky pytest timeout once more",
            "unrelated brand color palette work",
        ]
    )
    clusters = community_detection(vecs, threshold=0.5, min_community_size=2)
    assert any(len(c) >= 3 for c in clusters)  # the three pytest items group
    assert all(3 not in c for c in clusters if len(c) >= 3)  # the unrelated one excluded


def test_recurrence_gate_requires_distinct_sessions() -> None:
    # same engineer, same problem, but only across 2 sessions -> below floor of 3
    comps = [
        _comp("c1", "s1", "eng", "fix flaky pytest timeout"),
        _comp("c2", "s1", "eng", "fix flaky pytest timeout"),  # same session
        _comp("c3", "s2", "eng", "fix flaky pytest timeout"),
    ]
    clusters = cluster_compactions(comps, HashingEmbedder(), threshold=0.5)
    assert recurring(clusters, min_sessions=3) == []  # only 2 distinct sessions
    assert recurring(clusters, min_sessions=2)  # 2 sessions clears a floor of 2


# ── SKILL.md format ───────────────────────────────────────────────────────
def test_name_validation() -> None:
    assert validate_name("fix-flaky-tests") == []
    assert validate_name("Fix Tests")  # uppercase + space invalid
    assert validate_name("claude-helper")  # reserved word
    assert validate_name("x" * 65)  # too long


def test_description_validation() -> None:
    assert validate_description("Fixes flaky tests; use when pytest times out.") == []
    assert validate_description("")  # empty invalid
    assert validate_description("has <xml> tag")  # XML tags invalid
    assert validate_description("x" * 1025)  # too long


def test_repair_and_render() -> None:
    draft = repair_draft(SkillDraft(name="Fix Claude Tests!", description="ok <b>x</b>", body="do"))
    assert validate_name(draft.name) == []  # slugified + reserved word removed
    assert "claude" not in draft.name
    assert "<" not in draft.description
    md = render_skill_md(draft)
    assert md.startswith("---\n")
    assert f"name: {draft.name}\n" in md
    assert "description: \"" in md


def test_slugify_fallback() -> None:
    assert slugify_name("") == "mined-skill"
    assert slugify_name("Fix Flaky Tests") == "fix-flaky-tests"


# ── synthesis ─────────────────────────────────────────────────────────────
def _cluster():
    comps = [
        _comp("c1", "s1", "eng", "fix flaky pytest timeout"),
        _comp("c2", "s2", "eng", "fix flaky pytest timeout"),
        _comp("c3", "s3", "eng", "fix flaky pytest timeout"),
    ]
    return cluster_compactions(comps, HashingEmbedder(), threshold=0.5)[0]


def test_synthesize_with_llm_produces_valid_draft() -> None:
    good = json.dumps(
        {
            "name": "fix-flaky-tests",
            "description": "Stabilizes flaky tests; use when CI tests time out intermittently.",
            "body": "## Steps\n\n1. Reproduce.\n2. Add retry/await.\n",
        }
    )
    draft = synthesize(_cluster(), MockProvider(good))
    assert draft.name == "fix-flaky-tests"
    assert validate_draft(draft) == []


def test_synthesize_falls_back_on_garbage_or_no_llm() -> None:
    assert validate_draft(synthesize(_cluster(), MockProvider("not json"))) == []
    assert validate_draft(synthesize(_cluster(), None)) == []  # offline fallback


def test_fallback_draft_is_always_valid() -> None:
    assert validate_draft(fallback_draft(_cluster())) == []


# ── provenance ────────────────────────────────────────────────────────────
def test_provenance_records_evidence_and_hashes() -> None:
    cluster = _cluster()
    md = render_skill_md(fallback_draft(cluster))
    prov = make_provenance(cluster, md, now=_T0)
    assert prov.source == "manthana-skill-miner"
    assert prov.session_count == 3
    assert set(prov.evidence) == {"c1", "c2", "c3"}
    assert prov.content_hash.startswith("sha256:")
    assert make_provenance(cluster, md, now=_T0).content_hash == prov.content_hash  # deterministic
    # k-anonymized variant drops contributor names
    assert make_provenance(cluster, md, now=_T0, include_contributors=False).contributors is None


# ── end-to-end miner ──────────────────────────────────────────────────────
def test_miner_proposes_and_writes_skill(tmp_path: Path) -> None:
    comps = [
        _comp("c1", "s1", "eng", "fix flaky pytest timeout"),
        _comp("c2", "s2", "eng", "fix flaky pytest timeout"),
        _comp("c3", "s3", "eng", "fix flaky pytest timeout"),
        _comp("c4", "s4", "eng", "completely unrelated brand palette"),
    ]
    miner = SkillMiner(embedder=HashingEmbedder(), provider=None, threshold=0.5)
    proposals = miner.mine(comps, min_sessions=3, now=_T0)
    assert len(proposals) == 1  # only the recurring pytest pattern (3 sessions)
    p = proposals[0]
    assert validate_draft(p.draft) == []

    out = write_proposal(p, tmp_path)
    assert (out / "SKILL.md").read_text().startswith("---\n")
    assert json.loads((out / "provenance.json").read_text())["session_count"] == 3


# ── review fixes (regressions) ────────────────────────────────────────────
def test_embedder_uses_full_token_not_first_byte() -> None:
    e = HashingEmbedder()
    a, b = e.embed(["deploy the docker daemon", "debug that data dump"])  # share no real tokens
    assert cosine(a, b) < 0.5
    c, d = e.embed(["kubernetes rollout", "rollout kubernetes"])  # same tokens
    assert cosine(c, d) > 0.99


def test_slugify_cannot_reconstruct_reserved_word() -> None:
    name = slugify_name("antclaudehropic")  # removing 'claude' would re-form 'anthropic'
    assert validate_name(name) == []
    assert "anthropic" not in name and "claude" not in name


def test_control_chars_rejected_and_stripped() -> None:
    assert validate_description("bad\x00desc")  # rejected
    repaired = repair_draft(SkillDraft("ok-name", "clean\x00desc\x07more", "body"))
    assert "\x00" not in repaired.description and "\x07" not in repaired.description
    assert validate_description(repaired.description) == []


def test_synthesize_null_fields_fall_back() -> None:
    draft = synthesize(_cluster(), MockProvider('{"name":null,"description":null,"body":null}'))
    assert validate_draft(draft) == []
    assert draft.name != "none"  # deterministic fallback, not coerced "None"


def test_extract_json_prefers_real_answer_after_prose_example() -> None:
    real = '{"name":"real-skill","description":"does X; use when Y","body":"b"}'
    draft = synthesize(_cluster(), MockProvider(f'Example: {{"foo": 1}}\nHere it is: {real}'))
    assert draft.name == "real-skill"


def test_write_proposal_collision_does_not_clobber(tmp_path: Path) -> None:
    from manthana.agent.skillminer.miner import SkillProposal

    cl = _cluster()
    d1 = SkillDraft("dup-skill", "desc one; use when a", "body one")
    d2 = SkillDraft("dup-skill", "desc two; use when b", "body two")
    md1, md2 = render_skill_md(d1), render_skill_md(d2)
    p1 = SkillProposal(d1, md1, make_provenance(cl, md1, now=_T0), cl)
    p2 = SkillProposal(d2, md2, make_provenance(cl, md2, now=_T0), cl)
    t1 = write_proposal(p1, tmp_path)
    t2 = write_proposal(p2, tmp_path)
    assert t1.name == "dup-skill" and t2.name == "dup-skill-2"  # no clobber
    assert write_proposal(p1, tmp_path) == t1  # idempotent (same content hash)


def test_mine_rejects_unsafe_contributor_disclosure() -> None:
    import pytest

    with pytest.raises(ValueError):
        SkillMiner(embedder=HashingEmbedder()).mine(
            [_comp("c1", "s1", "e", "x")], min_contributors=2, include_contributors=True
        )


def test_mine_org_is_k_anonymized() -> None:
    from manthana.agent.skillminer import mine_org

    comps = [_comp(f"c{i}", f"s{i}", f"e{i}@x.com", "fix flaky pytest timeout") for i in range(4)]
    proposals = mine_org(comps, now=_T0)
    assert len(proposals) == 1
    assert proposals[0].provenance.contributor_count == 4
    assert proposals[0].provenance.contributors is None  # names dropped (k-anon)


def test_provenance_validation_is_strict() -> None:
    from dataclasses import replace

    from manthana.agent.skillminer.provenance import validate_provenance

    cl = _cluster()
    good = make_provenance(cl, render_skill_md(fallback_draft(cl)), now=_T0)
    assert validate_provenance(good) == []
    assert validate_provenance(replace(good, evidence=[]))  # empty evidence
    assert validate_provenance(replace(good, content_hash="nope"))  # bad hash prefix
    # contributor_count is 1 (one actor); a 2-name list must be flagged as a mismatch
    assert validate_provenance(replace(good, contributors=["a", "b"]))


def test_miner_redacts_secrets_from_mined_skill() -> None:
    secret = "AKIAIOSFODNN7EXAMPLE"
    comps = [
        _comp(f"c{i}", f"s{i}", "eng", f"deploy service with key {secret}", approach="ship it")
        for i in range(3)
    ]
    proposals = SkillMiner(embedder=HashingEmbedder(), provider=None, threshold=0.5).mine(
        comps, min_sessions=3, now=_T0
    )
    assert len(proposals) == 1
    blob = proposals[0].skill_md
    assert secret not in blob  # redacted before it reached the skill body/description
