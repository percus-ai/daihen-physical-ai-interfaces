from interfaces_backend.services.user_directory import (
    build_user_name,
    normalize_person_name,
    normalize_username,
    username_from_email,
)


def test_normalize_username_sanitizes_email_local_part():
    assert normalize_username("Tanaka.Tarou+admin") == "tanaka.tarou-admin"
    assert username_from_email("Tanaka.Tarou+admin@example.com") == "tanaka.tarou-admin"


def test_build_user_name_prefers_names_then_username_then_email():
    assert build_user_name(username="tanaka.tarou", first_name="Tarou", last_name="Tanaka", email="tanaka.tarou@example.com") == "Tanaka Tarou"
    assert build_user_name(username="tanaka.tarou", first_name="", last_name="", email="tanaka.tarou@example.com") == "tanaka.tarou"
    assert build_user_name(username="", first_name="", last_name="", email="tanaka.tarou@example.com") == "tanaka.tarou"


def test_normalize_person_name_trims_and_caps_length():
    assert normalize_person_name("  Tarou  ") == "Tarou"
    assert len(normalize_person_name("a" * 80)) == 64
