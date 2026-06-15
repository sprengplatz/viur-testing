# Dev-Mirror Mode

*Python side. Removes the "empty test namespace → second server"
friction by copying a live data slice into a per-developer namespace of
`viur-tests`.*

Dev-Mirror has two independent parts:

1. **Seeding** (out-of-band, occasional) — `viur-mirror` copies the live
   `(default)` database into a developer-chosen **namespace** of `viur-tests`.
2. **Tokenless browsing** (at boot, per developer) — lets you open your
   seeded slice in a browser without the `X-Viur-Test-Token` header.

## 1. Seeding — `viur-mirror`

There is no local emulator: `(default)` is the **live** database and
`viur-tests` is a separate **named** database in the same project. The copy
goes through the regular `google.cloud.datastore` client, which (since v2.x)
can target both a named `database` **and** a `namespace` — so each developer
copies the live slice into their own namespace:

```sh
# installed console script — copy into your namespace (--project is required):
viur-mirror --project my-gcp-project --target-namespace ak
# restrict to specific kinds:
viur-mirror --project my-gcp-project --target-namespace ak --kinds user,page
# from a source checkout without installing:
uv run python -m viur.testing.cli --project my-gcp-project --target-namespace ak
```

What it does:

- **PIN-gated** (fresh 6 digits, no TTY → abort) because it reads live data.
- Reads `(default)` **read-only** (`mirror.ReadOnlyClient`) and **excludes**
  viur-core secret/system kinds (`viur-conf` holds the hmacKey, `viur-session`,
  `viur-securitykey`, `viur-relations`, `file`/`file_rootNode`/`viur-blob-locks`).
  Widen with `--exclude`.
- Copies entity-by-entity into `viur-tests` / `ns=<target>`, re-keying each
  entity's own key **and every key-valued property (relations)** onto the
  target partition, in batches of up to 500 puts.

!!! info "Per-developer namespace — keys remapped onto the target"
    Each entity's **own key** is rebuilt in the target namespace, so your slice
    is isolated from other developers'. Key-valued *properties* (relations) are
    rewritten too — recursively through lists and embedded entities — onto the
    target partition (`database=viur-tests`, `namespace=<target>`). This is
    **mandatory**, not optional: a copied entity in `viur-tests` may not
    reference keys in the source `(default)` database, so Datastore rejects a
    verbatim copy. As a side effect, relations resolve **within** your copied
    slice. Re-run the script to refresh your slice.

!!! warning "Reads live production · data protection"
    Seeding reads the live database (read-only). That is a conscious
    relaxation of the "never reads production" guarantee. The read-only
    source client (`mirror.ReadOnlyClient`) makes writing back to `(default)`
    structurally impossible, but copying live data into a test slice can pull
    in personal data — review/extend `--exclude` for PII before running.

!!! note "Why not `gcloud` export/import?"
    The managed `gcloud datastore`/`firestore` export/import **cannot remap
    namespaces** — `--namespace-ids` / `--namespaces` is a *filter* on which
    source namespaces to include, never a destination. Imported entities are
    restored into the namespace they were exported from. A per-developer
    target namespace is therefore only reachable via a direct client copy (the
    "custom migration solution" the Google docs point to).

Requirements: an explicit `--project` (required — never inferred, since this
reads live data), application-default credentials
(`gcloud auth application-default login`), IAM to read `(default)` and write
`viur-tests`, and the `viur-tests` named database must already exist.

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

Then boot in **dev mode**, pointing the server at **your** namespace
(the one you copied into). Dev mode (`VIUR_TESTING=dev:<ns>`) is test
mode plus tokenless browsing:

```sh
VIUR_TESTING=dev:ak viur run develop
```

Before the real server boots, a fresh PIN gates arming tokenless browsing
for this dev server. Once armed, requests may skip the
`X-Viur-Test-Token` header — so you can just open the app against your
seeded slice.

It is gated, per request, by:

| Condition | Why |
|---|---|
| project id ∈ `tokenless_app_ids` | explicit per-project opt-in |
| `conf.instance.is_dev_server` | never opens a deployed instance |
| armed this boot (PIN-confirmed) | a human enabled it deliberately |

Tokenless only ever exposes the `viur-tests` slice — never `(default)`. The
Playwright runner is unaffected: its fixtures still inject the token and
`/_test/config/status` still issues one, so e2e runs unchanged; you simply
gain manual browsing on top.

!!! warning "Boot with the namespace you copied into"
    `viur-mirror --target-namespace ak` lands the data in `viur-tests` /
    `ns=ak`. The server must boot with the **same** namespace
    (`VIUR_TESTING=dev:ak`) or it points at an empty slice. `activate()`
    aligns the datastore client **and** the viur-core `Key` factory to that
    database + namespace, so reads and writes stay in your slice.

## Non-negotiables

- **No TTY → hard abort** (both the copy and tokenless arming). Do not use
  `dev` mode (`VIUR_TESTING=dev:<ns>`) in CI.
- **Wrong PIN → abort.** No retry; re-run for a fresh PIN.
- **Never into `(default)`.** `--target-database` may never be the live
  database — a hard guard with no override.
- **Tokenless can write.** A tokenless stray request could mutate your
  `viur-tests` namespace — re-run `viur-mirror` to restore it.
