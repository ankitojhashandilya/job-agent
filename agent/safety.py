"""Safety layer — intercepts destructive actions before execution.

The executor must never execute a blocked command.  The safety layer
checks every ``BrowserCommand`` before it reaches the executor and
blocks final-submission or destructive actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.execute import BrowserAction, BrowserCommand


_FINAL_ACTION_KEYWORDS = frozenset({
    "submit", "submit application", "send application",
    "finish", "complete application", "complete",
    "withdraw", "withdraw application",
    "delete", "remove", "reject",
})

_FINAL_TEXT_PATTERNS = [
    "submit", "finish", "complete", "withdraw",
    "delete", "remove", "reject",
    "send application",
]


@dataclass
class SafetyDecision:
    allowed: bool
    reason: str
    command: BrowserCommand | None = None


class Safety:
    """Intercepts commands and blocks destructive actions.

    Usage::

        decision = safety.check(command)
        if not decision.allowed:
            # do not execute
            ...

    The safety layer is stateless and stateless across checks.
    """

    @staticmethod
    def check(command: BrowserCommand) -> SafetyDecision:
        if command.action == BrowserAction.STOP_FOR_REVIEW:
            return SafetyDecision(
                allowed=False,
                reason=command.value or "Human review is required before proceeding.",
                command=command,
            )

        if command.action == BrowserAction.CLICK_BUTTON:
            return Safety._check_click(command)

        if command.action == BrowserAction.FILL_FIELD:
            return Safety._check_fill(command)

        return SafetyDecision(allowed=True, reason="Allowed", command=command)

    @classmethod
    def allow_user_confirmed_submit(
        cls,
        command: BrowserCommand,
        user_confirmed: bool,
    ) -> SafetyDecision:
        """Allow one final click only after an explicit human confirmation.

        This is deliberately separate from :meth:`check`, whose default
        behaviour always blocks final controls.  Callers must first identify a
        final control through ``check`` and collect a fresh confirmation from
        the user in the active terminal session.
        """
        decision = cls.check(command)
        if (
            user_confirmed
            and command.action == BrowserAction.CLICK_BUTTON
            and decision.reason.startswith("Final submission blocked")
        ):
            return SafetyDecision(
                allowed=True,
                reason="Final submission explicitly confirmed by the user.",
                command=command,
            )
        return decision

    @classmethod
    def _check_click(cls, command: BrowserCommand) -> SafetyDecision:
        target = (command.target or "").lower()
        btn_text = target.replace("button:", "").replace("_", " ").strip()

        if btn_text in _FINAL_ACTION_KEYWORDS:
            return SafetyDecision(
                allowed=False,
                reason=f"Final submission blocked: '{btn_text}'",
                command=command,
            )

        for pattern in _FINAL_TEXT_PATTERNS:
            if pattern in btn_text:
                return SafetyDecision(
                    allowed=False,
                    reason=f"Final submission blocked: '{btn_text}' (matched '{pattern}')",
                    command=command,
                )

        return SafetyDecision(allowed=True, reason="Allowed", command=command)

    @classmethod
    def _check_fill(cls, command: BrowserCommand) -> SafetyDecision:
        return SafetyDecision(allowed=True, reason="Allowed", command=command)
