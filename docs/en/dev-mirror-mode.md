# Development Mode

Development mode is the same safe test mode, scoped to your own Datastore
**namespace** so you can browse a realistic slice of data by hand — without the
"empty test database" friction. It combines two independent pieces:

1. **Seeding** — `viur-mirror` copies a slice of the live `(default)` database
   into a namespace of `viur-tests` (out-of-band, occasional).
2. **Manual browsing** — boot the dev server in that namespace and arm the
   cookie once via `/_test/config/enter`; then browse the test instance
   directly, hard navigations included.

The test token stays **fully enforced** throughout — manual browsing works
because the `viur-test-token` cookie rides along on every request (see
[ViUR3 Monkey Patches](viur3-patches.md)), not because any check is relaxed.

## Boot in your namespace

```sh
VIUR_TESTING=ak viur run develop
```

`VIUR_TESTING=<namespace>` boots test mode in that namespace (here `ak`);
`VIUR_TESTING=1` uses the default namespace. Each developer picks their own
namespace so seeded slices stay isolated.

## Arm manual browsing (the cookie)

Navigate once to:

```
http://localhost:8080/json/_test/config/enter
```

The backend responds with `Set-Cookie` (`SameSite=Strict; HttpOnly; Path=/`).
From then on you browse `http://localhost:8080/...` normally — hard navigation,
reloads, server-rendered pages: the cookie is attached automatically and the
token stays enforced. No PIN, no browser extension, no second proxy port.

## Seed your namespace — `viur-mirror`

The `viur-mirror` console script copies kinds from a database into your
`viur-tests` namespace. The project must be specified explicitly:

```sh
viur-mirror --project my-gcp-project --target-namespace ak
```

- The `(default)` database is hard-excluded as a **target** to prevent
  overwriting live data, and is read through a **read-only** client.
- **viur-core system kinds are excluded**: `viur-conf` (holds the hmacKey),
  `viur-session`, `viur-securitykey`.
- To avoid conflicts with file uploads, `viur-relations`, `file`,
  `file_rootNode` and `viur-blob-locks` are also excluded.

Consequence: only data is copied, no files. (A future update will also create
file copies.)

!!! warning "Seeding reads live production data"
    Seeding reads the live `(default)` database (read-only) and is PIN-gated. It
    can pull personal data into the test slice — review the `--exclude` list for
    PII before running.
