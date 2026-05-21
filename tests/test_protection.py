"""Unit tests for :mod:`viur.testing.protection`."""

from viur.testing import protect
from viur.testing.validator import ProductionGuardValidator


def test_protect_installs_guard_into_router(router_validators):
    protect()
    assert ProductionGuardValidator in router_validators


def test_protect_is_idempotent(router_validators):
    protect()
    protect()
    protect()
    assert router_validators.count(ProductionGuardValidator) == 1


def test_protect_is_safe_in_dev(conf_instance, router_validators):
    """``protect()`` does the same thing in dev or prod — the guard itself
    decides whether to fire per-request."""
    conf_instance.is_dev_server = True
    protect()
    assert ProductionGuardValidator in router_validators


def test_protect_is_safe_in_prod(conf_instance, router_validators):
    conf_instance.is_dev_server = False
    protect()
    assert ProductionGuardValidator in router_validators
