"""Redaction pipeline + Work/Personal-mode-to-sync-gate tests.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import UTC, datetime

from manthana.agent.config import Config, build_redactor
from manthana.agent.redaction import RedactionConfig, Redactor
from manthana.agent.store import Store
from manthana.agent.sync import eligible_for_sync
from manthana.schemas import BaseCompaction, Mode, Outcome, Role, Session, Surface, Turn

_T0 = datetime(2026, 1, 1, tzinfo=UTC)


# ── secret + PII redaction ───────────────────────────────────────────────
def test_detects_and_redacts_secrets() -> None:
    r = Redactor()
    text = (
        "key=AKIAIOSFODNN7EXAMPLE token: 'supersecretvalue' "
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789AB "
        "-----BEGIN RSA PRIVATE KEY-----"
    )
    found = set(r.detect(text))
    assert {"aws_key", "github_token", "private_key", "generic_secret"} <= found
    redacted = r.redact_text(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789AB" not in redacted
    assert "[REDACTED:aws_key]" in redacted


def test_redacts_pii_email_and_phone() -> None:
    r = Redactor()
    redacted = r.redact_text("reach me at jane.doe@example.com or +1 415-555-1234")
    assert "jane.doe@example.com" not in redacted
    assert "[REDACTED:email]" in redacted
    assert "555-1234" not in redacted


def test_pii_can_be_disabled() -> None:
    r = Redactor(RedactionConfig(redact_pii=False))
    redacted = r.redact_text("email me: a@b.com")
    assert "a@b.com" in redacted  # PII off -> left intact


def test_redact_turn_returns_copy_and_scrubs_fields() -> None:
    r = Redactor()
    turn = Turn(
        id="t1",
        session_id="s1",
        actor="e",
        seq=0,
        role=Role.tool,
        content="my email is a@b.com",
        tool_output="AKIAIOSFODNN7EXAMPLE leaked",
        tool_input={"note": "password='hunter2longenough'"},
    )
    redacted = r.redact_turn(turn)
    assert redacted is not turn
    assert turn.tool_output == "AKIAIOSFODNN7EXAMPLE leaked"  # original untouched
    assert "AKIAIOSFODNN7EXAMPLE" not in (redacted.tool_output or "")
    assert "a@b.com" not in (redacted.content or "")
    assert "hunter2longenough" not in str(redacted.tool_input)


def test_governance_detectors() -> None:
    r = Redactor()
    assert r.detect_approval_required("git push origin main --force")
    assert r.detect_approval_required("rm -rf /tmp/x")
    assert r.detect_approval_required("echo safe") == []
    assert r.detect_sensitive_path("/app/.env") is True
    assert r.detect_sensitive_path("/home/u/.ssh/id_rsa") is True
    assert r.detect_sensitive_path("/app/main.py") is False


def test_build_redactor_from_config() -> None:
    r = build_redactor(Config(redact_pii=False, redact_secrets=True))
    assert "a@b.com" in (r.redact_text("a@b.com") or "")
    assert "[REDACTED:aws_key]" in (r.redact_text("AKIAIOSFODNN7EXAMPLE") or "")


# ── Work/Personal toggle wired to the sync gate ──────────────────────────
def _session(sid: str, mode: Mode) -> Session:
    return Session(
        id=sid, actor="e", surface=Surface.claude_code, project="p", started_at=_T0, mode=mode
    )


def _released_compaction(sid: str) -> BaseCompaction:
    return BaseCompaction(
        id=f"c-{sid}",
        session_id=sid,
        actor="e",
        surface=Surface.claude_code,
        project="p",
        started_at=_T0,
        ended_at=_T0,
        duration_seconds=1.0,
        task_intent="t",
        approach="a",
        outcome=Outcome.success,
        released=True,
    )


def test_personal_toggle_removes_from_sync_eligibility() -> None:
    store = Store.open_memory()
    store.upsert_session(_session("s1", Mode.work))
    store.upsert_compaction(_released_compaction("s1"))

    by_id = {s.id: s for s in store.list_sessions()}
    assert eligible_for_sync(store.list_compactions(), by_id)  # work + released -> eligible

    assert store.set_session_mode("s1", Mode.personal) is True
    by_id = {s.id: s for s in store.list_sessions()}
    assert eligible_for_sync(store.list_compactions(), by_id) == []  # personal -> blocked


# ── review fixes: redaction completeness ──────────────────────────────────
_AWS = "AKIAIOSFODNN7EXAMPLE"


def test_redact_turn_scrubs_error_and_dict_keys() -> None:
    r = Redactor()
    turn = Turn(
        id="t",
        session_id="s",
        actor="e",
        seq=0,
        role=Role.tool,
        error=f"failed: {_AWS}",
        tool_input={"password='hunter2longenough'": "v", "note": _AWS},
    )
    red = r.redact_turn(turn)
    assert _AWS not in (red.error or "")  # error is scrubbed
    assert "hunter2longenough" not in str(red.tool_input)  # dict KEY scrubbed
    assert _AWS not in str(red.tool_input)  # dict value scrubbed


def test_redact_compaction_scrubs_subclass_and_friction_fields() -> None:
    from manthana.schemas import EngineeringCompaction, FrictionCategory, FrictionPoint

    r = Redactor()
    comp = EngineeringCompaction(
        id="c",
        session_id="s",
        actor="e",
        surface=Surface.claude_code,
        project="proj",
        started_at=_T0,
        ended_at=_T0,
        duration_seconds=1.0,
        task_intent="ok",
        approach="ok",
        outcome=Outcome.success,
        files_touched=[f".env holds {_AWS}"],
        friction_points=[
            FrictionPoint(category=FrictionCategory.loop, description=f"token {_AWS}")
        ],
    )
    red = r.redact_compaction(comp)
    assert isinstance(red, EngineeringCompaction)
    assert _AWS not in red.files_touched[0]  # subclass list field scrubbed
    assert _AWS not in red.friction_points[0].description  # friction scrubbed
    assert red.project == "proj"  # structural/grouping field preserved
    assert red.id == "c" and red.kind == "engineering"
