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
        # LinkedIn can fail before page load on some Windows/Chrome network
        # stacks when Chromium selects QUIC/HTTP3.  Use normal HTTPS/TCP for
        # deterministic automation; this changes transport only, not safety
        # behaviour or login state.
        args=["--start-maximized", "--disable-quic"],
    )
