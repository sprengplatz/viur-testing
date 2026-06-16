# ViUR3 Monkey Patches

viur-testing runs a ViUR3 / viur-core process against a **named** Datastore
database (default `viur-tests`) and an optional **namespace**. Neither viur-core
nor `google-cloud-datastore` fully support that out of the box, so test mode
applies a small set of runtime patches that bridge the gap.

All patches share two properties:

- **dev-server only** — installed from `activate()`; the sole exception is the
  production guard, installed by `protect()` in every environment.
- **idempotent** — re-activation (test re-entry) replaces the wrapper instead
  of stacking layers.

## 1. Datastore client swap

**Target:** `viur.core.db.transport.__client__`

**Why:** viur-core binds a single module-level `datastore.Client()` to the
default database at import time. Test mode must talk to the named test database
instead.

**What it does:** `activate()` builds a `datastore.Client(database=…, namespace=…)`,
proves it with a write+read probe roundtrip, and replaces
`transport.__client__` with it — *before* any further viur-core import, so every
later consumer sees the swapped client. This is why `activate()` must run at the
very top of `main.py`, before `viur.core.db.transport` is imported.

## 2. Key factory — inject database & namespace

**Target:** `viur.core.db.types.Key.__init__`

**Why:** viur-core's `Key` forwards only `project=` to
`google.cloud.datastore.Key`, never `database=` or `namespace=`. Against a
named-database client that mismatch makes every call fail with
`InvalidArgument: 400 mismatched databases within request`. Namespaces have the
same issue — writes land in the default namespace while reads come from the test
one, yielding silently empty results.

**What it does:** wraps `Key.__init__` so the `database` and `namespace` kwargs
default to the active client's values; explicit caller kwargs still win. The
original `__init__` is stashed on the wrapper, so re-activation unwraps before
re-wrapping (no stacking).

## 3. Legacy urlsafe keys tolerate named databases

**Target:** `google.cloud.datastore.key.Key.to_legacy_urlsafe`

**Why:** the stock method raises `ValueError("to_legacy_urlsafe only supports
the default database")` for any key with a `database` set.

**What it does:** wraps the Google method to temporarily clear `self._database`
around the original call and restore it in `finally`. The resulting urlsafe
string carries project + namespace + path (the database id is dropped) — safe in
a test process because every key targets the same database, which the key
factory patch (#2) fills back in on parse. Patched at the root (the Google
method) rather than viur-core's `__str__`, so it survives viur-core changes and
covers every call site.

## 4. Boot banner — show the active database

**Target:** `viur.core.setup`

**Why:** when the dev server boots, the single most important fact is *which*
datastore the process is wired to (prod-default vs. `viur-tests`).

**What it does:** wraps `viur.core.setup()` so that, while it runs,
`builtins.print` is temporarily replaced by a sniffer that detects viur-core's
`LOCAL DEVELOPMENT SERVER IS UP AND RUNNING` banner and injects `database = …`
(and `namespace = …`, when set) lines just before the banner trailer, matching
its width and style. The original `print` is restored as soon as `setup()`
returns, so nothing outside the banner window is affected. Width and trailer are
detected at runtime, so a future viur-core banner change degrades gracefully.

## 5. Request validators

**Target:** `viur.core.request.Router.requestValidators`

Two validators are appended to the router's class-level list:

- **`TokenValidator`** — installed by `activate()` (dev/test). Rejects every
  non-bootstrap request that lacks a matching `viur-test-token` cookie
  (constant-time compare). The `/_test/config/status`, `/_test/config/enter`
  and `/_test/config/finish` bootstrap paths bypass it so the runner (and the
  manual-browse navigation) can open a session before a cookie exists.
- **`ProductionGuardValidator`** — installed by `protect()` in **every**
  environment, and watches the `viur-test-token` **cookie** as a tripwire: on a
  non-dev server it 403s any request carrying that cookie, regardless of value;
  in dev it is a no-op (the `TokenValidator` owns the cookie there). A test
  cookie should never reach production, so the guard rejects it loudly instead
  of letting it fall through. See [Validators](api/validator.md).

Both registrations are membership-checked, so calling them twice is a no-op.

## 6. Closed-system allow-list

**Target:** `conf.security.closed_system_allowed_paths`

**Why:** many projects run with `conf.security.closed_system = True`, which 401s
any request whose path is not allow-listed — before routing. The `/_test/`
bootstrap and host-registered fixture submodules would be blocked even with a
valid token.

**What it does:** `activate()` extends the list with the wildcards `_test/*` and
`*/_test/*` (covering every render prefix and host-registered fixtures). Access
control on those paths is still enforced by the `TokenValidator` — the
allow-list only gets the request past the closed-system gate.
