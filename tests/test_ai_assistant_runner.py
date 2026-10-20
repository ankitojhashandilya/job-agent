import os
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from scripts.update_ai_assistant_runner import HELPERS, OLD_CANCEL, OLD_TIMEOUT, patch_runner


def helpers(monkeypatch, platform=None):
    namespace = {
        "os": SimpleNamespace(name=platform or os.name, environ={}),
        "subprocess": MagicMock(TimeoutExpired=subprocess.TimeoutExpired),
    }
    exec(HELPERS, namespace)
    return namespace


def test_timeout_is_configurable_and_invalid_values_fail_early(monkeypatch):
    function = helpers(monkeypatch)["_job_agent_timeout_seconds"]
    assert function() == 3600
    assert function({"JOB_AGENT_COMMAND_TIMEOUT": "7200"}) == 7200
    with pytest.raises(RuntimeError):
        function({"JOB_AGENT_COMMAND_TIMEOUT": "broken"})
    with pytest.raises(RuntimeError):
        function({"JOB_AGENT_COMMAND_TIMEOUT": "0"})


def test_windows_cancellation_stops_the_worker_tree_and_waits(monkeypatch):
    namespace = helpers(monkeypatch, "nt")
    process = MagicMock(pid=123)
    process.poll.return_value = None
    namespace["_terminate_job_agent_process"](process)
    assert namespace["subprocess"].run.call_args.args[0] == ["taskkill", "/PID", "123", "/T", "/F"]
    process.wait.assert_called_once_with(timeout=5)


def test_non_windows_termination_escalates_only_if_needed(monkeypatch):
    namespace = helpers(monkeypatch, "posix")
    process = MagicMock()
    process.poll.return_value = None
    process.wait.side_effect = [subprocess.TimeoutExpired("test", 5), 0]
    namespace["_terminate_job_agent_process"](process)
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert process.wait.call_count == 2


def test_installer_is_guarded_idempotent_and_validates_before_launch():
    original = (
        "import os, subprocess, time\n"
        "def run_job_agent_command_stream(env_overrides=None):\n"
        "    process = subprocess.Popen([])\n"
        "    deadline = time.time() + 900\n"
        "    while True:\n"
        "        if should_cancel():\n"
        + OLD_CANCEL
        + "        if time.time() > deadline:\n"
        + OLD_TIMEOUT
        + "\n"
    )
    updated = patch_runner(original)
    assert patch_runner(updated) == updated
    assert updated.index("command_timeout =") < updated.index("process = subprocess.Popen")
    assert "deadline = time.time() + command_timeout" in updated
    compile(updated, "runner.py", "exec")
    with pytest.raises(RuntimeError, match="no file was changed"):
        patch_runner("unsupported source")
