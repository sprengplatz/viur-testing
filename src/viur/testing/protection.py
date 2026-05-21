"""
Production-side header guard.

The full :class:`~viur.testing.validator.TokenValidator` is only installed
inside :func:`viur.testing.activate`, which itself only runs on a local dev
server. In a cloud deployment that means the ``X-Viur-Test-Token``
header is *ignored* rather than rejected — a request carrying the
header simply falls through to viur-core's normal auth path.

:func:`protect` closes that gap by installing the
:class:`~viur.testing.validator.ProductionGuardValidator` into
``Router.requestValidators``. The host calls it once at startup in
*every* environment:

- In a dev process where :func:`viur.testing.activate` has already run, the
  guard is a no-op (the full :class:`~viur.testing.validator.TokenValidator`
  owns the header logic).
- In a cloud process, the guard turns any request carrying the test
  token header into an immediate 403, regardless of the header's value.

Order matters in dev: call :func:`activate` *before* :func:`protect`.
:func:`protect` imports ``viur.core.request`` which transitively loads
``viur.core.db.transport`` and creates the default datastore client.
If :func:`activate` runs afterwards, the
``_require_transport_not_loaded`` guard will refuse.
"""


def protect() -> None:
    """Install :class:`ProductionGuardValidator` into the viur-core router.

    Idempotent — calling twice is a no-op. Safe to call in any
    environment.
    """
    from viur.core.request import Router  # noqa: PLC0415
    from .validator import ProductionGuardValidator  # noqa: PLC0415

    if ProductionGuardValidator not in Router.requestValidators:
        Router.requestValidators.append(ProductionGuardValidator)
