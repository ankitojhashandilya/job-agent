from pathlib import Path


PROFILE_DIR = Path(__file__).resolve().parent / "browser-profile"


def launch_linkedin_context(playwright):
    PROFILE_DIR.mkdir(exist_ok=True)
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        channel="chrome",
        headless=False,
        viewport={"width": 1440, "height": 900},
        locale="en-IN",
        timezone_id="Asia/Kolkata",
        args=["--start-maximized"],
    )
