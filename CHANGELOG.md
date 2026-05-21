# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `viur.testing.setup()` and `viur.testing.register_modules()` — two
  one-liner host wrappers around the underlying primitives. ``main.py``
  is reduced to ``import viur.testing; viur.testing.setup()`` and
  ``modules/__init__.py`` to ``viur.testing.register_modules(globals())``.
  Both are no-ops in production (env var unset / state inactive).
- `viur.testing.activate()` — atomic test-mode activation. Order of
  checks: ``viur.core.db.transport`` not yet imported, then
  ``conf.instance.is_dev_server`` true, then builds a
  ``datastore.Client(database=…)`` against the test database (default
  ``viur-tests``), runs a synchronous probe roundtrip, patches
  ``transport.__client__``, monkey-patches
  ``viur.core.db.types.Key.__init__`` to inject ``database=`` on every
  newly constructed Key, extends ``conf.security.closed_system_allowed_paths``
  with the bootstrap endpoints, primes ``ConfigModule`` and installs
  the request validator. No on-disk state.
- `viur.testing.protect()` and `ProductionGuardValidator` — host
  installs the guard via `protect()` in every environment. On a
  non-dev server, any request carrying an ``X-Viur-Test-Token`` header
  is rejected with 403 regardless of the header's value. In dev the
  guard is a no-op (the full `TokenValidator` already handles the
  header).
- `viur.testing._test.TestModule` — host-mountable container module
  under ``/_test``. Carries ``json = True`` so viur-core's
  ``__build_app`` registers it under the JSON renderer. Refuses to
  instantiate outside a local dev server *or* when `activate()` has
  not run yet — the structural last line of defence against
  accidental production mounts and against silent
  "mounted-but-unactivated" states.
- `viur.testing._test.config.ConfigModule` — the bootstrap config
  submodule mounted as ``/_test/config``. Carries the per-process
  class-level state (``_database``, ``_project_id``, ``_token``) and
  the same two mount guards as `TestModule` so a host that bypasses
  the container and mounts `ConfigModule` directly is still caught.
  Endpoint bodies are emitted as JSON strings (``Content-Type:
  application/json`` + ``json.dumps``) so viur-core's WSGI layer
  forwards a proper JSON body rather than a Python ``repr`` of a
  dict. Exposes two endpoints:
  - ``POST /_test/config/status`` — re-verifies dev-server + datastore
    database, then reads/creates the session token entity in the test
    database (kind ``viur-tests``, entity ``auth-token``) and returns
    it to the runner. Response carries ``token``, ``token_hash``,
    ``database``, ``project_id``, ``version``. Idempotent. POST-only
    so a parallel browser tab cannot drive-by trigger the endpoint
    via a simple GET (CORS preflight stops the cross-origin POST).
  - ``POST /_test/config/finish`` — re-verifies, deletes the token
    entity, clears the in-process token. Test-mode itself stays
    armed.
- `viur.testing.validator.TokenValidator` — `RequestValidator`
  rejecting every non-bootstrap request that lacks a matching
  ``X-Viur-Test-Token`` header (constant-time compare). Auto-installed
  by `activate()`. Paths ending in ``/_test/config/status`` or
  ``/_test/config/finish`` bypass the token check so the runner can
  bootstrap a session before one exists.
- `viur.testing.require_test_mode()` — runner preflight: calls
  ``/_test/config/status``, verifies the response, returns a
  `ServerStatus` carrying the session token.
- `viur.testing.finish()` — runner cleanup: deletes the token entity
  via ``POST /_test/config/finish``.
- The top-level `viur.testing/__init__.py` only re-exports the
  viur-core-free surface (`activate`, `protect`, `require_test_mode`,
  `finish`, plus dataclasses/constants). The heavy classes
  (`TestModule`, `ConfigModule`, `TokenValidator`,
  `ProductionGuardValidator`) live in their concrete submodules and
  must be imported from there — so ``import viur.testing`` does not
  trigger ``viur.core`` before the datastore client swap.
- Test suite against ``viur-light-mock`` + local stubs, 100% line +
  branch coverage.
- ``smoke_test.py`` — end-to-end script that walks every refuse path
  in a fresh subprocess and additionally exercises ``activate()`` all
  the way through to a real ``datastore.Client(database="viur-tests")``
  + probe roundtrip when run against a workstation with valid GCP
  credentials.

### Lessons learned from booting against a real viur-core project

These five surprises only surfaced when the package was wired into the
real ``deploy/`` project and not into mocks. Each one is now built in:

1. **Reserved Datastore kind prefix.** Original ``PROBE_KIND`` was
   ``__viur_test_probe__``. Google Cloud Datastore reserves ``__*__``
   for system-internal use and 400s the write with ``The kind … is
   reserved``. Renamed to ``viur-test-probe``.
2. **Multi-database Key construction.** viur-core's ``Key`` class
   forwards ``project=`` to ``google.cloud.datastore.Key`` but **not**
   ``database=``. With a named-DB client every Key viur-core builds
   is for the default database, and Datastore rejects the call with
   ``mismatched databases within request``. Fixed by
   ``_patch_key_factory`` which wraps ``Key.__init__`` to default
   ``database=`` to the patched client's database.
3. **Closed-system gate.** Many host projects set
   ``conf.security.closed_system = True`` in their own config.py.
   Once on, every URL not in
   ``conf.security.closed_system_allowed_paths`` returns 401 *before*
   the route is resolved. ``activate()`` now extends that allow-list
   with the two bootstrap endpoints (plus wildcards for arbitrary
   render prefixes) so ``/_test/config/status`` + ``/_test/config/finish``
   reach the module.
4. **Render-name opt-in.** ``__build_app`` only registers a module
   class for a given renderer if ``getattr(cls, render_name, False)``
   is truthy. Without ``TestModule.json = True`` the routes are
   silently not mounted. The class now carries that flag.
5. **Class vs. instance in modules namespace.** ``__build_app``
   iterates ``vars(modules)`` and only picks up subclasses of Module
   (or already-instanced ``InstancedModule``). A bare module
   instance is silently skipped. The host-side wiring documented in
   the README registers ``TestModule`` as a *class*, not as an
   instance.

### Fixed

- ``PROBE_KIND`` is now ``viur-test-probe`` (see lesson 1 above).
- Status and finish endpoints return ``json.dumps(...)`` with
  ``Content-Type: application/json`` instead of raw Python dicts
  (viur-core's WSGI layer would otherwise stringify the dict via
  ``str()``, sending Python repr to the client).
- ``_require_dev_server`` runs **after** ``_require_transport_not_loaded``
  in ``activate()``. The dev-server check reads
  ``conf.instance.is_dev_server`` which triggers the full
  ``viur.core/__init__.py`` import chain (including
  ``viur.core.db.transport``); running the transport-not-loaded
  check first cleanly distinguishes "host already imported viur-core"
  (refuse) from "we are about to import it ourselves" (allowed).

[Unreleased]: https://github.com/sprengplatz/viur-testing/commits/main
