"""AI Browser Agent for automated job applications.

This package implements a perception-action loop that replaces
hardcoded ATS-specific workflows with LLM-driven decision making.
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
from agent.execute import Executor, BrowserCommand, BrowserAction, ExecutionResult

__all__ = [
    "observe_page",
    "Executor",
    "BrowserCommand",
    "BrowserAction",
    "ExecutionResult",
    "PageSnapshot",
    "FormField",
    "Button",
    "FileInput",
    "ToolCall",
    "ActionRecord",
    "ApplicationState",
    "TaskInfo",
]
