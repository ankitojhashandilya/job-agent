"""Browser Agent V2 — the application automation pipeline.

Strict one-way dependency:

    automation  -->  agent  -->  playwright

Every module inside ``automation`` communicates through the immutable
canonical contracts in :mod:`automation.types` — never raw dicts and
never Playwright objects. ATS adapters are NOT implemented; the engine
is ATS-agnostic by design.
"""

from automation.context import ApplicationContext
from automation.engine import ApplicationEngine, make_advance
from automation.executor import TaskExecutor
from automation.llm_planner import LLMPlanner
from automation.planner import Planner
from automation.questions import understand_page
from automation.resolver import SemanticFieldResolver
from automation.retry import RetryEngine
from automation.rule_planner import RulePlanner
from automation.tasks import add_dependencies, extract_tasks
from automation.timeline import Timeline
from automation.types import (
    ApplicationResult,
    ExecutionResult,
    PlannerDecision,
    Question,
    QuestionType,
    Task,
    TaskAction,
    TaskState,
    TimelineEvent,
    VerificationOutcome,
    VerificationReport,
)
from automation.verification import ApplicationVerifier

__all__ = [
    "ApplicationContext",
    "ApplicationEngine",
    "make_advance",
    "TaskExecutor",
    "LLMPlanner",
    "Planner",
    "understand_page",
    "SemanticFieldResolver",
    "RetryEngine",
    "RulePlanner",
    "add_dependencies",
    "extract_tasks",
    "Timeline",
    "ApplicationResult",
    "ExecutionResult",
    "PlannerDecision",
    "Question",
    "QuestionType",
    "Task",
    "TaskAction",
    "TaskState",
    "TimelineEvent",
    "VerificationOutcome",
    "VerificationReport",
    "ApplicationVerifier",
]
