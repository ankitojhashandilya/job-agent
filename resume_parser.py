# resume_parser.py

import json
import re
from pathlib import Path

from pypdf import PdfReader

from config import (
    KNOWN_DOMAINS,
    KNOWN_SKILLS,
    MAX_SKILLS,
    RESUME_PATH,
    RESUME_PROFILE_PATH,
)


def extract_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))

    pages = []

    for page in reader.pages:
        text = page.extract_text()

        if text:
            pages.append(text)

    return "\n".join(pages)


def extract_skills(text: str) -> list[str]:
    found = set()

    lowered = text.lower()

    for skill in KNOWN_SKILLS:
        if skill.lower() in lowered:
            found.add(skill)

    return sorted(found)[:MAX_SKILLS]


def extract_domains(text: str) -> list[str]:
    found = set()

    lowered = text.lower()

    for domain in KNOWN_DOMAINS:
        if domain.lower() in lowered:
            found.add(domain)

    return sorted(found)


def extract_years(text: str) -> int:
    match = re.search(
        r"(\d+)\+?\s+years?\s+of\s+experience",
        text,
        re.IGNORECASE,
    )

    if match:
        return int(match.group(1))

    return 0


def extract_current_company(text: str) -> str:
    patterns = [
        r"([A-Za-z &]+)\s+[—-]\s+Senior Data Engineer",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            return match.group(1).strip()

    return ""

def leadership_signal(text: str) -> bool:
    signals = [
        "mentor",
        "technical lead",
        "architecture",
        "code review",
        "roadmap",
        "cross-functional",
        "delivery",
        "onboarding",
        "stakeholder",
    ]

    lowered = text.lower()

    return any(signal in lowered for signal in signals)


def build_profile(text: str) -> dict:
    return {
        "years_of_experience": extract_years(text),
        "skills": extract_skills(text),
        "domains": extract_domains(text),
        "current_company": extract_current_company(text),
        "leadership_experience": leadership_signal(text),
        "target_roles": [
            "Lead Data Engineer",
            "Principal Data Engineer",
            "Staff Data Engineer",
        ],
    }


def main():
    if not RESUME_PATH.exists():
        raise SystemExit(
            f"Resume not found: {RESUME_PATH}"
        )

    print("Reading resume...")

    text = extract_text(RESUME_PATH)

    profile = build_profile(text)

    RESUME_PROFILE_PATH.write_text(
        json.dumps(profile, indent=2),
        encoding="utf-8",
    )

    print(
        f"Resume profile saved to "
        f"{RESUME_PROFILE_PATH}"
    )

    print(json.dumps(profile, indent=2))


if __name__ == "__main__":
    main()
