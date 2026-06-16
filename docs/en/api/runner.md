# Runner API

The Python-side functions and data classes for talking to a
viur-testing-armed server. Used by hosts that drive their own
runner (a custom smoke harness, an internal CI tool, …).

The canonical Playwright e2e wiring lives in the npm companion
package [`@spltz/viur-testing`](https://www.npmjs.com/package/@spltz/viur-testing)
and is driven by [`createGlobalSetup()`](../guarded-mode.md) — the
primitives below are the same handshake, exposed for Python
callers that want to reuse it.

## require_test_mode

::: viur.testing.runner.require_test_mode
    options:
      heading_level: 3
      show_source: true

## finish

::: viur.testing.runner.finish
    options:
      heading_level: 3
      show_source: true

## ServerStatus

::: viur.testing.runner.ServerStatus
    options:
      heading_level: 3
      show_source: true

## TestModePreflightError

::: viur.testing.runner.TestModePreflightError
    options:
      heading_level: 3
      show_source: true
