# Guarded Mode

Guarded Mode is a browsing variant for testing against live data. This is risky
and should only be used with good reason, by developers who know what their
tests do to the system. No safety mechanism is active in the backend;
consequently the `_test/` endpoints are unavailable either. To compensate, the
Playwright runner forces a PIN entry before starting — as a deliberate
confirmation and to prevent use in CI/CD.

The mode activates automatically as soon as the backend is not running in test
mode — even if that happens by accident.

## The PIN challenge

The prompt shows the target URL again for verification:

```
$ npx playwright test

[viur-testing] probing https://staging.example.com/json/_test/config/status ...

⚠  GUARDED MODE
   Target backend:  https://staging.example.com
   The backend is NOT in test mode. Tests will interact with
   the live application — no test database, no token guard,
   no _test/ fixture endpoints. Specs that use _test
   infrastructure are auto-skipped.

   Confirm by typing:   8 4 1 7 3 9

   > _
```

## What changes inside the suite

Tests that use `_test/` infrastructure are skipped — reported as *skipped*, not
*failed*.

A run report looks like this:

```
Running 12 tests using 1 worker

  ✓ tests/public-landing.spec.ts:8:3   › renders hero (340ms)
  ✓ tests/public-landing.spec.ts:14:3  › nav links work (220ms)
  -  tests/user-login.spec.ts:5:3      › uses _test infrastructure …
  -  tests/user-login.spec.ts:18:3     › uses _test infrastructure …
  ✓ tests/footer.spec.ts:6:3            › privacy link present (180ms)
  ...
```

## Detecting the mode at runtime

If you need to branch inside a spec or fixture (rare — most specs should not
need to), inspect `process.env.VIUR_TESTING_MODE`:

```ts
import { MODE_ENV_VAR } from "@spltz/viur-testing"

if (process.env[MODE_ENV_VAR] === "guarded") {
  // running against a live backend, no _test infrastructure
}
```
