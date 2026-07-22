import csv
import os
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
CSV_OUTPUT = PROJECT_DIR / "job_results.csv"


def main() -> None:
    try:
        import gspread
    except ImportError as error:
        raise SystemExit(
            "Missing dependency. Run:\n"
            ".\\venv\\Scripts\\python.exe -m pip install gspread google-auth"
        ) from error

    credentials_path = os.environ.get(
        "GOOGLE_APPLICATION_CREDENTIALS",
        str(PROJECT_DIR / "google_service_account.json"),
    )

    sheet_name = os.environ.get("JOB_AGENT_SHEET_NAME", "Job Tracker")

    if not Path(credentials_path).exists():
        raise SystemExit(
            "Google credentials file not found.\n"
            f"Expected: {credentials_path}\n\n"
            "Create a Google Cloud service account, download its JSON key, "
            "save it as C:\\job-agent\\google_service_account.json, then share "
            "the 'Job Tracker' Google Sheet with the service account email."
        )

    client = gspread.service_account(filename=credentials_path)
    spreadsheet = client.open(sheet_name)
    worksheet = spreadsheet.sheet1

    with CSV_OUTPUT.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.reader(file))

    worksheet.clear()
    if rows:
        worksheet.update(rows, value_input_option="USER_ENTERED")

    print(f"Uploaded {max(len(rows) - 1, 0)} jobs to Google Sheet: {sheet_name}")


if __name__ == "__main__":
    main()
