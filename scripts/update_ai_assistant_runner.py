"""Install the resumable-discovery runner fix in a local AI Assistant project.

Usage: python scripts/update_ai_assistant_runner.py --project C:/AI/Projects/ai-assistant
The pure transformation is tested here so the local integration fix is versioned
alongside job-agent even when AI Assistant itself is not a Git checkout.
"""

import argparse
from pathlib import Path

HELPERS = """
def _job_agent_timeout_seconds(env_overrides=None):
    values = os.environ if env_overrides is None else {**os.environ, **env_overrides}
    try:
        timeout = int(values.get("JOB_AGENT_COMMAND_TIMEOUT", "3600"))
    except (TypeError, ValueError) as error:
        raise RuntimeError("JOB_AGENT_COMMAND_TIMEOUT must be a number of seconds.") from error
    if timeout < 60:
        raise RuntimeError("JOB_AGENT_COMMAND_TIMEOUT must be at least 60 seconds.")
    return timeout


def _terminate_job_agent_process(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        # Windows virtualenv launchers spawn a second Python process. Stop
        # this command's entire tree so timed-out scoring cannot run on unseen.
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True, timeout=10, check=False,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


"""

OLD_CANCEL = """            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                emit("Process did not exit after terminate; killing it.")
                process.kill()
"""
OLD_TIMEOUT = """            process.kill()
            raise TimeoutError("Job-agent command timed out after 900 seconds.")"""


def patch_runner(source: str) -> str:
    if "def _job_agent_timeout_seconds(" in source:
        # Upgrade the initial installer too: validate configuration before
        # launching any process, so an invalid timeout cannot orphan a worker.
        old = "    command_timeout = _job_agent_timeout_seconds(env_overrides)\n    deadline ="
        if old in source:
            source = source.replace(old, "    deadline =", 1)
            source = source.replace(
                "    process = subprocess.Popen(",
                "    command_timeout = _job_agent_timeout_seconds(env_overrides)\n"
                "    process = subprocess.Popen(",
                1,
            )
        return source
    replacements = [
        ("def run_job_agent_command_stream(", HELPERS + "def run_job_agent_command_stream("),
        (
            "    process = subprocess.Popen(",
            "    command_timeout = _job_agent_timeout_seconds(env_overrides)\n"
            "    process = subprocess.Popen(",
        ),
        (
            "    deadline = time.time() + 900",
            "    deadline = time.time() + command_timeout\n"
            '    emit(f"Run budget: {command_timeout}s; completed jobs are saved for reuse.")',
        ),
        (OLD_CANCEL, "            _terminate_job_agent_process(process)\n"),
        (
            OLD_TIMEOUT,
            '            emit("Run budget exceeded. Stopping the command '
            'and retaining saved jobs.")\n'
            "            _terminate_job_agent_process(process)\n"
            '            raise TimeoutError(f"Job-agent command timed out after '
            '{command_timeout} seconds. "\n'
            '                               "Saved jobs are retained; rerun '
            'to reuse completed work.")',
        ),
    ]
    for old, new in replacements:
        if source.count(old) != 1:
            raise RuntimeError(
                "AI Assistant runner differs from the supported version; no file was changed."
            )
        source = source.replace(old, new, 1)
    compile(source, "job_agent.py", "exec")
    return source


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, type=Path)
    args = parser.parse_args()
    target = args.project.resolve() / "src" / "agents" / "job_agent.py"
    original = target.read_text(encoding="utf-8")
    updated = patch_runner(original)
    if updated == original:
        print("AI Assistant runner is already updated.")
        return
    backup = target.with_suffix(".py.before-resume-fix.bak")
    if not backup.exists():
        backup.write_text(original, encoding="utf-8")
    target.write_text(updated, encoding="utf-8")
    print("AI Assistant runner updated. Restart its web server to activate the change.")


if __name__ == "__main__":
    main()
