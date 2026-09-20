"""ATS detection and support policy for the production browser agent.

The agent only treats explicitly supported platforms as automation targets.
Everything else is a deliberate human handoff, never a false success.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse

from agent.types import PageSnapshot


class ATSPlatform(str, Enum):
    LINKEDIN = "linkedin_easy_apply"
    WORKDAY = "workday"
    GREENHOUSE = "greenhouse"
    UNKNOWN = "unknown"


class ATSCapability(str, Enum):
    SUPPORTED = "supported"
    MANUAL_REQUIRED = "manual_required"
    LOGIN_REQUIRED = "login_required"
    CAPTCHA_DETECTED = "captcha_detected"
    JOB_UNAVAILABLE = "job_unavailable"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class ATSAssessment:
    platform: ATSPlatform
    capability: ATSCapability
    reason: str = ""


def assess_ats(snapshot: PageSnapshot) -> ATSAssessment:
    """Classify a page and say whether the agent may automate it."""
    page_type = snapshot.page_type.lower()
    if page_type == "login_required":
        return ATSAssessment(ATSPlatform.UNKNOWN, ATSCapability.LOGIN_REQUIRED, "Login is required.")
    if page_type == "captcha_detected":
        return ATSAssessment(ATSPlatform.UNKNOWN, ATSCapability.CAPTCHA_DETECTED, "CAPTCHA detected.")
    if page_type == "external_apply_started":
        return ATSAssessment(
            ATSPlatform.LINKEDIN,
            ATSCapability.SUPPORTED,
            "LinkedIn confirmed that your profile was shared; inspecting for a supported external destination.",
        )
    if page_type in {"unavailable", "redirect"}:
        return ATSAssessment(ATSPlatform.UNKNOWN, ATSCapability.JOB_UNAVAILABLE, "Job is unavailable.")

    domain = (snapshot.domain or "").lower()
    if domain.endswith("linkedin.com"):
        return ATSAssessment(ATSPlatform.LINKEDIN, ATSCapability.SUPPORTED)
    if "myworkdayjobs.com" in domain or domain.endswith("workday.com"):
        return ATSAssessment(ATSPlatform.WORKDAY, ATSCapability.SUPPORTED)
    if domain.endswith("greenhouse.io"):
        return ATSAssessment(ATSPlatform.GREENHOUSE, ATSCapability.SUPPORTED)
    if domain:
        return ATSAssessment(
            ATSPlatform.UNKNOWN,
            ATSCapability.UNSUPPORTED,
            f"Unsupported ATS domain: {domain}",
        )
    return ATSAssessment(ATSPlatform.UNKNOWN, ATSCapability.MANUAL_REQUIRED, "No ATS domain detected.")


def is_supported_ats_url(url: str) -> bool:
    """Return whether a link explicitly points to a supported application ATS."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return (
        "myworkdayjobs.com" in host
        or host.endswith("workday.com")
        or host.endswith("greenhouse.io")
    )


def forward_labels(platform: ATSPlatform) -> tuple[str, ...]:
    """Return allow-listed non-final navigation controls for an ATS."""
    shared = ("Continue", "Next", "Review", "Review application", "Save and continue")
    if platform is ATSPlatform.LINKEDIN:
        # Do not click LinkedIn's generic Apply button: it can hand off to an
        # external, unsupported ATS.  Only Easy Apply is in the supported
        # automation contract.
        return ("Easy Apply", *shared)
    if platform is ATSPlatform.WORKDAY:
        return ("Apply Manually", "Start Application", *shared)
    if platform is ATSPlatform.GREENHOUSE:
        return ("Apply for this job", "Apply", *shared)
    return shared


__all__ = [
    "ATSAssessment", "ATSCapability", "ATSPlatform", "assess_ats",
    "forward_labels", "is_supported_ats_url",
]
