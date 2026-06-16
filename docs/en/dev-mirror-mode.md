# Development Mode

Development mode is a relaxed variant of test mode: it loosens the backend rules
far enough that requests may skip the test token (tokenless browsing). This
gives you a full development environment — including Admin requests and normal
browsing, which carry no token.

In return, additional safeguards apply in the backend:

- **PIN on start** – the dev server can only be armed after PIN confirmation;
  this prevents use in CI/CD.
- **Namespace mandatory** – without a namespace the mode does not start. It
  operates exclusively in `viur-tests`, never on the live database.
- **Application-ID allowlisting** – the GCP project id must be explicitly
  enabled for tokenless access.

## Allow and use an application ID

The allowlist of tokenless-permitted GCP project ids lives in code – so it is
reviewed in PRs and does not drift in a dotfile:

```python
import viur.testing
viur.testing.setup(tokenless_app_ids=["my-project-id"])

from viur.core import setup as core_setup
import modules, render
app = core_setup(modules, render)
```

Then boot in **development mode** and point the server at **your** namespace.
Syntax: `VIUR_TESTING=dev:<ns>`

```sh
VIUR_TESTING=dev:ak viur run develop
```

Before the real server boots, a fresh PIN gates arming. Once armed, requests may
omit the `X-Viur-Test-Token` header — so you can open the app directly in the
browser.

## Mirror the database

The `viur-mirror` script copies kinds from a database into your `viur-tests`
namespace. The project must be specified explicitly:

```sh
viur-mirror --project my-gcp-project --target-namespace ak
```

- The `(default)` database is hard-excluded as a **target** to prevent
  overwriting live data.
- **viur-core system kinds are excluded**: `viur-conf` (holds the hmacKey),
  `viur-session`, `viur-securitykey`.
- To avoid conflicts with file uploads, `viur-relations`, `file`,
  `file_rootNode` and `viur-blob-locks` are also excluded.

Consequence: only data is copied, no files. (A future update will also create
file copies.)
