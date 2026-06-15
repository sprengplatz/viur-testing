"""
Light-weight constants shared across the package.

Lives in its own module so the request validator, the activation function
and the runner-side helpers can pick them up without importing the
:mod:`viur.testing._test.config` module — which would pull in ``viur.core`` and
transitively the default datastore client.
"""

TOKEN_HEADER = "X-Viur-Test-Token"
"""Header name that callers must set on every non-bootstrap request."""

PROBE_KIND = "viur-test-probe"
"""Datastore kind used for the boot-time roundtrip probe.

Plain (no leading underscores) because Google Cloud Datastore reserves
``__*__`` kind names for system-internal use and rejects any write to
them with ``InvalidArgument: 400 The kind ... is reserved``.
"""

TOKEN_KIND = "viur-tests"
"""Datastore kind that holds the session token entity."""

TOKEN_ENTITY_NAME = "auth-token"
"""Name of the singleton token entity inside :data:`TOKEN_KIND`."""

TOKEN_PROPERTY = "token"
"""Name of the property on the entity that stores the token string."""

DEFAULT_DATABASE = "viur-tests"
"""Name of the named Datastore database that holds the test data."""

BOOTSTRAP_ACTIONS: frozenset[str] = frozenset({"status", "finish"})
"""Trailing path segments that may be reached without a session token.

The status endpoint is what *issues* the token in the first place, so it
must be reachable without one. The finish endpoint must stay reachable
even after the token has been wiped, so the session can be cleanly torn
down. Both endpoints re-verify dev-server + database themselves.

The validator (:func:`viur.testing.validator._is_bootstrap_path`) accepts
exactly ``/<renderer>?/_test/config/<action>`` paths where ``<action>``
is one of these values and ``<renderer>`` is a single optional segment
(``json``, ``vi``, ``html``, ...). Anything deeper or differently shaped
is treated as a regular request and requires the token.
"""

MIRROR_EXCLUDE_KINDS: frozenset[str] = frozenset({
    "viur-conf",
    "viur-session",
    "file",
    "file_rootNode",
    "viur-blob-locks",
    "viur-securitykey",
    "viur-relations",
})
"""Datastore kinds the ``viur-mirror`` copy (:mod:`viur.testing.cli`) must
never copy from the live ``(default)`` database — viur-core secret /
per-instance system state (verified against viur-core 3.x):

- ``viur-conf`` — the singleton ``Key("viur-conf", "viur-conf")`` entity; the
  ``hmacKey`` lives as a *property* on it (not a separate kind), so excluding
  this kind keeps the secret out of the copy entirely.
- ``viur-session`` — ``Session.kindName``; sessions are per-instance and must
  not leak into the test slice.
- ``viur-securitykey`` — short-lived per-session security keys; per-instance.
- ``viur-relations`` — viur-core's relation index; rebuilt by the instance,
  copying it would carry stale source-namespace references.
- ``file`` / ``file_rootNode`` / ``viur-blob-locks`` — blob bookkeeping; the
  underlying blobs live in the bucket, not in the test namespace.

The copy additionally skips ``__*__`` reserved kinds. The ``viur-tests``
database keeps its own ``viur-conf``/hmacKey + admin user from viur-core's
first-boot startup tasks.

The copy pulls in whatever kinds you do NOT exclude — widen this (e.g. to keep
PII-heavy kinds out of the test slice) via the script's ``--exclude`` flag.
"""
