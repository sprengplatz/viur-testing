# Design: Single `VIUR_TESTING` env var with `mode:namespace` grammar

*Status: approved (brainstorming) — ready for implementation plan.*
*Date: 2026-06-15. Repo: `viur-testing` (branch `feat/devmode`).*

## Problem

Booting the dev server in Dev Mode currently requires three environment
variables that overlap heavily in intent:

```sh
VIUR_TESTING_ENABLE=1 VIUR_TESTING_NAMESPACE=ak VIUR_TESTING_TOKENLESS=1 viur run develop
```

- Setting a namespace already implies you want test mode on.
- Dev Mode practically always wants tokenless browsing.

Three booleans/strings for what is really one decision ("which mode, which
slice") is cumbersome and error-prone.

## Goal

Collapse the three server-side boot variables into **one** variable,
`VIUR_TESTING`, whose value encodes the mode and (optionally) the namespace.

```sh
VIUR_TESTING=dev:ak viur run develop
```

Non-goals: the Playwright runner's own `VIUR_TESTING_MODE` (test/guarded
detection) is unrelated and stays as is. This change is purely the
server-side boot path.

## Grammar & semantics

Value form: `<mode>[:<namespace>]`.

| Value | Mode | Namespace | Effect |
|---|---|---|---|
| unset / `""` / `0` / `off` / `false` | off | — | no `activate()`, only `protect()` |
| `1` / `true` / `on` / `test` | test | `(default)` | datastore swap to `viur-tests`, default ns |
| `test:ak` | test | `ak` | datastore swap, ns=`ak` |
| `dev` | **error** | — | dev requires a namespace (see Hardening) |
| `dev:ak` | dev | `ak` | test mode + tokenless browsing armed, ns=`ak` |
| anything else (`foo`, `dev:`, …) | **error** | — | hard boot error, fail loud |

Decisions locked in:

- **`1`/`true`/`on` are aliases for `test`** — preserves the reflexive
  `VIUR_TESTING=1`.
- **`off`/`false`/`0`/empty/unset all mean off.**
- **`dev` implies tokenless** — the separate `TOKENLESS` env var is removed.
- **Unknown mode keyword → hard boot error** (consistent with the package's
  fail-loud philosophy). Same for a `:` with an empty mode or `dev` with an
  empty namespace.

### Hardening: `dev` requires a namespace

`viur-mirror` forces `--target-namespace` (no default), so a seeded Dev slice
*always* lives in a named namespace. `VIUR_TESTING=dev` without `:ns` would
point at an empty slice — a guaranteed mistake. Therefore:

- `dev` with no namespace → **hard error** with an actionable message, e.g.
  *"viur-testing: dev mode requires a namespace — use VIUR_TESTING=dev:<ns>."*
- `test` with no namespace remains valid (the default slice is a legitimate
  single-developer setup).

## Python API

`setup()` loses three env-var parameters and the implicit tokenless var, and
gains a single `env_var` plus explicit `mode`/`namespace` overrides.

Before:

```python
def setup(*, enable_env_var="VIUR_TESTING_ENABLE", database=DEFAULT_DATABASE,
          namespace=None, namespace_env_var="VIUR_TESTING_NAMESPACE",
          api_dir="testing", tokenless_app_ids=None,
          tokenless_env_var=TOKENLESS_ENV_VAR): ...
```

After:

```python
def setup(*, env_var="VIUR_TESTING", mode=None, namespace=None,
          database=DEFAULT_DATABASE, api_dir="testing",
          tokenless_app_ids=None): ...
```

- `env_var` — name of the single variable (default `"VIUR_TESTING"`).
- `mode` / `namespace` — explicit overrides; when given they win over the env
  var, so a host can hardcode behaviour in `main.py`. When both are `None`,
  the env var is parsed.
- `tokenless_app_ids` stays (it is the in-code project-id whitelist); tokenless
  is now *armed* when the resolved mode is `dev`, not via a separate env var.

### New parsing module

A small, fully-testable `viur/testing/mode.py`:

```python
def parse_spec(value: str | None) -> tuple[str, str | None]:
    """Parse a VIUR_TESTING value into (mode, namespace).

    Returns ("off", None) for off-values. Raises ValueError on unknown
    mode keywords, empty mode before ':', or dev without a namespace.
    """
```

- Mode constants (`MODE_OFF`, `MODE_TEST`, `MODE_DEV`) and the alias sets live
  here (or in `constants.py` — implementer's choice, kept together).
- Resolution order in `setup()`: explicit `mode`/`namespace` kwargs →
  else `parse_spec(os.environ.get(env_var))`.
- `setup()` then: off → only `protect()`; test → `activate()`; dev →
  `activate()` + `arm_tokenless_browsing()`.

## Clean break — removed surface

Removed entirely (no fallback, no deprecation shim):

- env vars `VIUR_TESTING_ENABLE`, `VIUR_TESTING_NAMESPACE`,
  `VIUR_TESTING_TOKENLESS`
- constant `TOKENLESS_ENV_VAR`
- `setup()` params `enable_env_var`, `namespace_env_var`, `tokenless_env_var`

Rationale: pre-1.0; `ENABLE`/`NAMESPACE` are barely deployed and Dev-Mirror /
`TOKENLESS` are still unreleased on `feat/devmode`.

## Affected files

- **Code:** `src/viur/testing/constants.py`, `__init__.py`, `activation.py`,
  `mirror.py`, new `src/viur/testing/mode.py`
- **Tests:** `tests/test_activation.py`, `test_package.py`, `test_runner.py`,
  new `tests/test_mode.py`, `tests/conftest.py` — must keep 100 % coverage
- **Docs:** `README.md`, `docs/getting-started.md`, `docs/dev-mirror-mode.md`,
  `CHANGELOG.md` (one `[Unreleased]` entry, marked Breaking, with a migration
  line)
- **Playwright (text/comments only — runner never sets these vars):**
  `playwright/src/bin/init.ts`, `playwright/bin/init.mjs`,
  `playwright/src/test-mode.ts`, `playwright/src/vite-plugin.ts`

## Testing

- `test_mode.py`: table-driven `parse_spec` cases — every row of the grammar
  table above, including each alias and every error path (unknown keyword,
  `dev` without ns, empty mode before `:`).
- `test_activation.py` / `test_package.py`: `setup()` honours `env_var`,
  explicit `mode`/`namespace` overrides beat the env var, dev arms tokenless,
  off only calls `protect()`.
- 100 % branch coverage retained (enforced by `--cov-fail-under=100`).

## Migration (for the CHANGELOG)

```
- BREAKING: the three boot env vars VIUR_TESTING_ENABLE / _NAMESPACE /
  _TOKENLESS are replaced by a single VIUR_TESTING=<mode>[:<namespace>].
    VIUR_TESTING_ENABLE=1                                  → VIUR_TESTING=1   (or =test)
    VIUR_TESTING_ENABLE=1 VIUR_TESTING_NAMESPACE=ak        → VIUR_TESTING=test:ak
    VIUR_TESTING_ENABLE=1 VIUR_TESTING_NAMESPACE=ak \
      VIUR_TESTING_TOKENLESS=1                             → VIUR_TESTING=dev:ak
  dev mode now requires a namespace.
```
