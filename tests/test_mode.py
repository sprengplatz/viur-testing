"""Tests for viur.testing.mode — the VIUR_TESTING value parser."""

import pytest

from viur.testing.mode import parse_spec


@pytest.mark.parametrize(
    "value, expected",
    [
        # off-values → disabled
        (None, (False, None)),
        ("", (False, None)),
        ("   ", (False, None)),
        ("0", (False, None)),
        ("off", (False, None)),
        ("OFF", (False, None)),
        ("false", (False, None)),
        # on-values → enabled, default namespace
        ("1", (True, None)),
        ("true", (True, None)),
        ("on", (True, None)),
        ("ON", (True, None)),
        # anything else → enabled, namespace verbatim
        ("ak", (True, "ak")),
        (" ak ", (True, "ak")),  # surrounding whitespace stripped
        ("Prod", (True, "Prod")),  # namespace stays case-sensitive
        # former mode keywords are now ordinary namespace names
        ("test", (True, "test")),
        ("dev", (True, "dev")),
        ("dev:ak", (True, "dev:ak")),  # no separator anymore — verbatim
    ],
)
def test_parse_spec(value, expected):
    assert parse_spec(value) == expected
