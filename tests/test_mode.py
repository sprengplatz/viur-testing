"""Tests for viur.testing.mode — the VIUR_TESTING value parser."""

import pytest

from viur.testing.mode import (
    MODE_DEV,
    MODE_OFF,
    MODE_TEST,
    parse_spec,
    validate_spec,
)


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, (MODE_OFF, None)),
        ("", (MODE_OFF, None)),
        ("   ", (MODE_OFF, None)),
        ("0", (MODE_OFF, None)),
        ("off", (MODE_OFF, None)),
        ("OFF", (MODE_OFF, None)),
        ("false", (MODE_OFF, None)),
        ("1", (MODE_TEST, None)),
        ("true", (MODE_TEST, None)),
        ("on", (MODE_TEST, None)),
        ("test", (MODE_TEST, None)),
        ("TEST", (MODE_TEST, None)),
        ("test:ak", (MODE_TEST, "ak")),
        (" test : ak ", (MODE_TEST, "ak")),
        ("dev:ak", (MODE_DEV, "ak")),
        ("DEV:AK", (MODE_DEV, "AK")),  # namespace stays case-sensitive
    ],
)
def test_parse_spec_valid(value, expected):
    assert parse_spec(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "dev",        # dev requires a namespace
        "dev:",       # empty namespace after colon
        "test:",      # empty namespace after colon
        ":ak",        # empty mode before colon
        "foo",        # unknown mode keyword
        "off:ak",     # off does not take a namespace
    ],
)
def test_parse_spec_invalid(value):
    with pytest.raises(ValueError):
        parse_spec(value)


def test_validate_spec_dev_requires_namespace():
    with pytest.raises(ValueError):
        validate_spec(MODE_DEV, None)


def test_validate_spec_allows_dev_with_namespace():
    validate_spec(MODE_DEV, "ak")  # no raise


def test_validate_spec_allows_test_without_namespace():
    validate_spec(MODE_TEST, None)  # no raise
