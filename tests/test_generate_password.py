import string

from generate_password import generate_password


def test_generated_password_meets_strength_requirements():
    password = generate_password(24)

    assert len(password) == 24
    assert any(character in string.ascii_lowercase for character in password)
    assert any(character in string.ascii_uppercase for character in password)
    assert any(character in string.digits for character in password)
    assert any(character in "!@#$%^&*_-+=" for character in password)


def test_generated_password_rejects_short_lengths():
    try:
        generate_password(15)
    except ValueError as error:
        assert "at least 16" in str(error)
    else:
        raise AssertionError("Expected a short password to be rejected")
