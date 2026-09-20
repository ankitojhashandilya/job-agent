"""Deterministic case routing for browser-application pages."""

from __future__ import annotations

from enum import Enum

from agent.ats import ATSCapability, ATSPlatform, assess_ats
from agent.types import PageSnapshot


class ApplicationCase(str, Enum):
    LOGIN = "login"
    CAPTCHA = "captcha"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    LINKEDIN_ENTRY = "linkedin_entry"
    EXTERNAL_HANDOFF = "external_handoff"
    APPLICATION_FORM = "application_form"
    UNKNOWN_LAYOUT = "unknown_layout"


def route_case(snapshot: PageSnapshot) -> ApplicationCase:
    """Classify the page using only deterministic, observable signals."""
    if snapshot.page_type == "external_apply_started":
        return ApplicationCase.EXTERNAL_HANDOFF
    assessment = assess_ats(snapshot)
    if assessment.capability is ATSCapability.LOGIN_REQUIRED:
        return ApplicationCase.LOGIN
    if assessment.capability is ATSCapability.CAPTCHA_DETECTED:
        return ApplicationCase.CAPTCHA
    if assessment.capability is ATSCapability.JOB_UNAVAILABLE:
        return ApplicationCase.UNAVAILABLE
    if assessment.capability is not ATSCapability.SUPPORTED:
        return ApplicationCase.UNSUPPORTED
    if (
        assessment.platform is ATSPlatform.LINKEDIN
        and snapshot.page_type == "job_details"
    ):
        return ApplicationCase.LINKEDIN_ENTRY
    if snapshot.page_type == "application_form":
        return ApplicationCase.APPLICATION_FORM
    return ApplicationCase.UNKNOWN_LAYOUT
