"""Generate a high-entropy password without storing it anywhere.

Copy the displayed password directly into your password manager.  This script
does not read or write candidate data, email addresses, accounts, or Git files.
"""

from __future__ import annotations

import argparse
import secrets
import string


def generate_password(length: int = 24) -> str:
    """Return a password containing upper/lower/digit/symbol characters."""
    if length < 16:
        raise ValueError("Password length must be at least 16 characters.")
    groups = (string.ascii_lowercase, string.ascii_uppercase, string.digits, "!@#$%^&*_-+=")
    characters = [secrets.choice(group) for group in groups]
    alphabet = "".join(groups)
    characters.extend(secrets.choice(alphabet) for _ in range(length - len(characters)))
    secrets.SystemRandom().shuffle(characters)
    return "".join(characters)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate a password; it is never saved.")
    parser.add_argument("--length", type=int, default=24, help="Password length (minimum: 16).")
    args = parser.parse_args(argv)
    print(generate_password(args.length))


if __name__ == "__main__":
    main()
