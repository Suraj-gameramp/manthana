"""Action dispatcher.

Routes trigger events to registered handlers, enforcing the governance the
actions catalog requires before any handler runs:

  1. Personal-mode exclusion (hard; personal sessions contribute to no action).
  2. Consent (engineer opt-out for a category suppresses it).
  3. Cooldown (per action+actor window).
  4. Confidence threshold (if the handler reports one).

Every evaluation — fired, suppressed, or failed — is written to the action audit
log, so actions are correctable and visible rather than authoritative.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from manthana.schemas import Action, ActionAuditEntry, ActionOutcome, ConsentState, Mode

from ..store import Store
from .base import ActionContext, ActionHandler, TriggerEvent


class Dispatcher:
    """Registers action handlers and dispatches trigger events to them."""

    def __init__(self, store: Store, handlers: list[ActionHandler] | None = None) -> None:
        self.store = store
        self.ctx = ActionContext(store)
        self.handlers: list[ActionHandler] = list(handlers or [])

    def register(self, handler: ActionHandler) -> ActionHandler:
        self.handlers.append(handler)
        return handler

    def dispatch(
        self, event: TriggerEvent, *, now: datetime | None = None
    ) -> list[ActionAuditEntry]:
        now = now or datetime.now(UTC)
        session = self.store.get_session(event.session_id) if event.session_id else None
        entries: list[ActionAuditEntry] = []

        for handler in self.handlers:
            if not handler.handles(event):
                continue
            action = handler.action

            # 1. Trust gate — FAIL CLOSED. The local dispatcher only handles
            #    session-scoped events; an unresolvable session (None id or an
            #    unknown id) is excluded, mirroring sync.eligible_for_sync.
            #    Personal-mode sessions are excluded from all actions.
            if session is None:
                entries.append(
                    self._log(action, event, now, ActionOutcome.suppressed, "session_unresolved")
                )
                continue
            if session.mode is Mode.personal:
                entries.append(
                    self._log(
                        action, event, now, ActionOutcome.suppressed, "personal_mode_excluded"
                    )
                )
                continue

            # 2. Consent: engineer opt-out for this category.
            consent = self.store.get_consent(event.actor, action.id)
            if consent is not None and consent.state is ConsentState.opt_out:
                entries.append(
                    self._log(action, event, now, ActionOutcome.suppressed, "consent_opt_out")
                )
                continue

            # 3. Cooldown.
            if action.cooldown_seconds:
                last = self.store.last_fired_at(action.id, event.actor)
                if last is not None and (now - last).total_seconds() < action.cooldown_seconds:
                    entries.append(
                        self._log(action, event, now, ActionOutcome.suppressed, "cooldown")
                    )
                    continue

            # 4. Run; respect a reported confidence threshold.
            try:
                result = handler.run(event, self.ctx)
            except Exception as exc:  # noqa: BLE001 - never let one action break others
                entries.append(
                    self._log(
                        action, event, now, ActionOutcome.failed, f"error:{type(exc).__name__}"
                    )
                )
                continue

            if (
                action.confidence_threshold is not None
                and result.confidence is not None
                and result.confidence < action.confidence_threshold
            ):
                entries.append(
                    self._log(
                        action,
                        event,
                        now,
                        ActionOutcome.suppressed,
                        "below_confidence_threshold",
                        confidence=result.confidence,
                    )
                )
                continue

            entries.append(
                self._log(
                    action,
                    event,
                    now,
                    result.outcome,
                    result.trigger_condition,
                    confidence=result.confidence,
                    details=result.details,
                )
            )
        return entries

    def _log(
        self,
        action: Action,
        event: TriggerEvent,
        now: datetime,
        outcome: ActionOutcome,
        trigger_condition: str,
        *,
        confidence: float | None = None,
        details: dict[str, object] | None = None,
    ) -> ActionAuditEntry:
        entry = ActionAuditEntry(
            id=f"audit-{uuid.uuid4().hex[:12]}",
            action_id=action.id,
            actor=event.actor,
            fired_at=now,
            trigger_condition=trigger_condition,
            confidence=confidence,
            outcome=outcome,
            details=details or {},
        )
        self.store.add_audit(entry)
        return entry


__all__ = ["Dispatcher"]
