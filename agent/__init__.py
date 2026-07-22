"""AI Browser Agent for automated job applications.

This package implements a perception-action loop that replaces
hardcoded ATS-specific workflows with LLM-driven decision making.

Modules:
    types: Shared data models for the agent's internal API.
    observe: Page observation layer — converts a Playwright page
        into a structured, token-efficient snapshot.
    # Future modules (planned in roadmap):
    #   plan: LLM-based action planner.
    #   execute: Playwright action executor.
    #   safety: Submit-action guard.
    #   verify: Goal state verifier.
    #   agent: Main execution loop.
"""

from agent.types import (
    ActionRecord,
    ApplicationState,
    Button,
    FileInput,
    FormField,
    PageSnapshot,
    TaskInfo,
    ToolCall,
)

from agent.observe import observe_page

__all__ = [
    "observe_page",
    "PageSnapshot",
    "FormField",
    "Button",
    "FileInput",
    "ToolCall",
    "ActionRecord",
    "ApplicationState",
    "TaskInfo",
]
