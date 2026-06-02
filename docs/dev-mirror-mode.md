# Dev-Mirror Mode

*Python side. Removes the "empty test namespace → second server"
friction by seeding the shared `viur-tests` database from live data.*

Dev-Mirror has two independent parts:

1. **Seeding** (out-of-band, occasional) — a managed `gcloud` export/import
   copies the live `(default)` database into `viur-tests`.
2. **Tokenless browsing** (at boot, per developer) — lets you open the
   seeded slice in a browser without the `X-Viur-Test-Token` header.

## 1. Seeding — `scripts/dev_mirror_import.py`

There is no local emulator: `(default)` is the **live** database and
`viur-tests` is a separate **named** database in the same project. Named
databases can only be export/imported via the managed Firestore Admin
surface, which the `gcloud` CLI wraps:

```sh
uv run python scripts/dev_mirror_import.py --bucket gs://my-bucket/dev-mirror
# restrict to specific kinds:
uv run python scripts/dev_mirror_import.py --bucket gs://b/p --kinds user,page
```

What it does:

- **PIN-gated** (fresh 6 digits, no TTY → abort) because it reads live data.
- Reads `(default)` **read-only** and **excludes** `viur-conf` (holds the
  hmacKey) and `viur-session` already at export, so secrets never reach the
  bucket. Widen with `--exclude`.
- `gcloud firestore export (default) → GCS`, then `import GCS → viur-tests`;
  `gcloud` blocks until both jobs finish (minutes).

!!! info "No namespace remap — shared slice"
    Managed import preserves keys **1:1** (only the database changes), so
    relations stay intact **without re-keying** — but the data lands in
    `viur-tests`' **default namespace**. Every developer therefore shares one
    seeded slice; there is **no per-developer namespace isolation** in this
    mode. Re-run the script to refresh the shared slice.

!!! warning "Reads live production · data protection"
    Seeding reads the live database (read-only). That is a conscious
    relaxation of the "never reads production" guarantee. The read-only
    source client (`mirror.ReadOnlyClient`) makes writing back to `(default)`
    structurally impossible, but copying live data into a test slice can pull
    in personal data — review/extend `--exclude` for PII before running.

Requirements: `gcloud` authenticated, a GCS bucket, and Datastore
import/export IAM (e.g. `roles/datastore.importExportAdmin`).

## 2. Tokenless browsing — at boot

In `main.py`, pass the whitelist of GCP project ids allowed to browse
tokenless (kept in code so it is reviewed in PRs, not drifting in a dotfile):

```python
import viur.testing
viur.testing.setup(tokenless_app_ids=["my-project-id"])

from viur.core import setup as core_setup
import modules, render
app = core_setup(modules, render)
```

Then boot with the opt-in env var:

```sh
VIUR_TESTING_ENABLE=1 VIUR_TESTING_TOKENLESS=1 viur run develop
```

Before the real server boots, a fresh PIN gates arming tokenless browsing
for this dev server. Once armed, requests may skip the
`X-Viur-Test-Token` header — so you can just open the app against the
seeded slice.

It is gated, per request, by:

| Condition | Why |
|---|---|
| project id ∈ `tokenless_app_ids` | explicit per-project opt-in |
| `conf.instance.is_dev_server` | never opens a deployed instance |
| armed this boot (PIN-confirmed) | a human enabled it deliberately |

Tokenless only ever exposes the `viur-tests` slice — never `(default)`.
Since the seed lands in the default namespace, tokenless does **not**
require a per-developer namespace. The Playwright runner is unaffected:
its fixtures still inject the token and `/_test/config/status` still issues
one, so e2e runs unchanged; you simply gain manual browsing on top.

!!! note "Boot without a namespace"
    With managed seeding the data is in `viur-tests`' **default** namespace,
    so boot **without** `VIUR_TESTING_NAMESPACE` — a namespace would point
    the server at an empty slice.

## Non-negotiables

- **No TTY → hard abort** (both the seed script and tokenless arming). Do
  not set `VIUR_TESTING_TOKENLESS` in CI.
- **Wrong PIN → abort.** No retry; re-run for a fresh PIN.
- **Shared slice.** A tokenless stray request could mutate the shared
  `viur-tests` data — re-seed via the script to restore it.
