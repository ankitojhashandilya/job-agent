
# run_pipeline.py

import json
import subprocess
import sys
import time
from pathlib import Path

from config import (
    APPLICATIONS_JSON,
    JOB_RESULTS_JSON,
    RESUME_PROFILE_PATH,
)


PROJECT_DIR = Path(__file__).resolve().parent


def run_script(
    script_name: str,
    required_output: Path | None = None,
    required_min_items: int | None = None,
    continue_on_failure: bool = False,
) -> bool:
    """
    Execute a Python script and validate output.

    Returns True if successful.
    """

    script_path = PROJECT_DIR / script_name

    if not script_path.exists():
        message = f"[ERROR] Missing script: {script_name}"

        if continue_on_failure:
            print(message)
            return False

        raise FileNotFoundError(message)

    print("\n" + "=" * 80)
    print(f"Running: {script_name}")
    print("=" * 80)

    start = time.time()

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=PROJECT_DIR,
            text=True,
            capture_output=False,
            check=True,
        )

        duration = round(time.time() - start, 1)

        print(
            f"\n✓ Completed {script_name}"
            f" ({duration} seconds)"
        )

        if required_output:
            if not required_output.exists():
                raise FileNotFoundError(
                    f"{required_output.name} was not generated."
                )

            if required_min_items is not None:
                data = json.loads(
                    required_output.read_text(
                        encoding="utf-8"
                    )
                )

                if not isinstance(data, list):
                    raise ValueError(
                        f"{required_output.name} must contain a JSON list."
                    )

                if len(data) < required_min_items:
                    raise ValueError(
                        f"{required_output.name} contains {len(data)} items; "
                        f"expected at least {required_min_items}."
                    )

        return True

    except subprocess.CalledProcessError as error:
        duration = round(time.time() - start, 1)

        print(
            f"\n✗ {script_name} failed "
            f"after {duration} seconds."
        )

        if continue_on_failure:
            return False

        raise error


def print_summary() -> None:
    """
    Display pipeline summary.
    """

    print("\n" + "=" * 80)
    print("PIPELINE SUMMARY")
    print("=" * 80)

    if RESUME_PROFILE_PATH.exists():
        print(
            f"✓ Resume profile: "
            f"{RESUME_PROFILE_PATH.name}"
        )
    else:
        print("✗ Resume profile missing")

    if JOB_RESULTS_JSON.exists():
        print(
            f"✓ Job results: "
            f"{JOB_RESULTS_JSON.name}"
        )
    else:
        print("✗ Job results missing")

    if APPLICATIONS_JSON.exists():
        print(
            f"✓ Applications: "
            f"{APPLICATIONS_JSON.name}"
        )
    else:
        print(
            "- Applications not generated "
            "(apply stage skipped)"
        )

    print("\nPipeline completed.")


def main() -> None:
    """
    Orchestrates the complete job-agent workflow.
    """

    print("\nJOB AGENT PIPELINE")
    print("=" * 80)

    #
    # Stage 1
    #
    print("\nStage 1: Resume Parsing")

    run_script(
        "resume_parser.py",
        required_output=RESUME_PROFILE_PATH,
    )

    #
    # Stage 2
    #
    print("\nStage 2: LinkedIn Job Discovery")

    run_script(
        "linkedin_score_jobs.py",
        required_output=JOB_RESULTS_JSON,
        required_min_items=1,
    )

    #
    # Stage 3
    #
    print("\nStage 3: Google Sheets Export")

    run_script(
        "google_sheets_export.py",
        continue_on_failure=True,
    )

    #
    # Stage 4
    #
    apply_choice = (
        input(
            "\nApply to top jobs? "
            "(y/n): "
        )
        .strip()
        .lower()
    )

    if apply_choice == "y":
        print("\nStage 4: Applications")

        run_script(
            "apply_top_jobs.py",
            continue_on_failure=True,
        )
    else:
        print(
            "\nSkipping application stage."
        )

    print_summary()


if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        print(
            "\n\nPipeline interrupted "
            "by user."
        )

    except Exception as error:
        print(
            f"\n\nPipeline failed:\n{error}"
        )
        raise
