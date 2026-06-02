#!/usr/bin/env python
"""
Dev-Mirror via MANAGED Datastore export/import.

Seeds the ``viur-tests`` database (default namespace) from the live
``(default)`` database using ``gcloud firestore export`` / ``import`` — the
managed, server-side mechanism that supports *named* databases (the Python
``datastore_admin_v1`` client only ever touches ``(default)`` and has no
``database_id`` field; named-DB export/import goes through the Firestore Admin
surface, which ``gcloud`` wraps).

Run it occasionally to (re)seed the SHARED test slice. It is a heavyweight
operation: ``gcloud`` blocks until the export and the import jobs finish
(minutes), round-tripping through a GCS bucket.

Key properties of the managed path
-----------------------------------
- **No key/namespace remap.** Managed import preserves keys 1:1 (only the
  database changes), so ``(default)`` lands in ``viur-tests``' **default**
  namespace and relations stay intact *without* re-keying. Per-developer
  namespace isolation is therefore NOT possible this way — every developer
  shares the imported slice (the accepted trade-off for this mode).
- **Reads live production.** Export is read-only on the source (it never
  mutates ``(default)``), but it does copy live data — hence the PIN gate.
- **Secrets stay out of the bucket.** ``viur-conf`` (holds the hmacKey) and
  ``viur-session`` are excluded from the export, so they never reach GCS.
  ``viur-tests`` keeps its own ``viur-conf``/hmacKey from first boot.

Safety gate
-----------
A fresh 6-digit PIN (reused from :mod:`viur.testing.pin`) is required every
run — no TTY means no run. The prompt names the project, source, target and
bucket so you see exactly what is about to be copied.

Requirements
------------
- ``gcloud`` CLI installed and authenticated (``gcloud auth login`` +
  ``gcloud auth application-default login``).
- A GCS bucket you can write to and read from.
- IAM roles to export/import Datastore entities (e.g.
  ``roles/datastore.importExportAdmin``) and to access the bucket.

Usage
-----
::

    uv run python scripts/dev_mirror_import.py --bucket gs://my-bucket/dev-mirror
    uv run python scripts/dev_mirror_import.py --bucket gs://b/p --kinds user,page
    uv run python scripts/dev_mirror_import.py --bucket gs://b/p \\
        --target-database viur-tests --namespace-ids ""
"""

from __future__ import annotations

import argparse
import datetime
import shutil
import subprocess
import sys

from google.cloud import datastore

from viur.testing.constants import MIRROR_EXCLUDE_KINDS
from viur.testing.mirror import ReadOnlyClient
from viur.testing.pin import PinChallengeError, run_pin_challenge

# viur-core secret / per-instance kinds that must never be copied (verified
# against viur-core 3.x: hmacKey is a property on the "viur-conf" entity, so
# excluding that kind covers the secret; "viur-session" is Session.kindName).
DEFAULT_EXCLUDE = set(MIRROR_EXCLUDE_KINDS)


def enumerate_kinds(exclude: set[str]) -> list[str]:
    """Return the user-data kinds in ``(default)`` minus *exclude* and the
    reserved ``__*__`` metadata kinds. Uses a read-only client so the live
    database cannot be mutated by accident."""
    client = ReadOnlyClient(datastore.Client())
    kinds: list[str] = []
    for meta in client.query(kind="__kind__").fetch():
        name = meta.key.name
        if not name or name.startswith("__") or name in exclude:
            continue
        kinds.append(name)
    return kinds


def _run_gcloud(args: list[str], *, capture: bool = False) -> str:
    print("+ gcloud " + " ".join(args))
    result = subprocess.run(
        ["gcloud", *args], check=True, text=True,
        capture_output=capture,
    )
    return (result.stdout or "").strip() if capture else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Managed export/import seed of viur-tests from (default).",
    )
    parser.add_argument("--bucket", required=True, help="gs://bucket/prefix for the export")
    parser.add_argument("--source-database", default="(default)")
    parser.add_argument("--target-database", default="viur-tests")
    parser.add_argument("--project", default=None, help="GCP project (default: ADC project)")
    parser.add_argument(
        "--kinds", default="",
        help="comma-separated kinds to copy; default = all kinds minus --exclude",
    )
    parser.add_argument(
        "--exclude", default=",".join(sorted(DEFAULT_EXCLUDE)),
        help="comma-separated kinds to never copy (secrets/sessions)",
    )
    parser.add_argument(
        "--namespace-ids", default=None,
        help="restrict to these source namespace ids (default: all)",
    )
    args = parser.parse_args(argv)

    if shutil.which("gcloud") is None:
        print(
            "error: gcloud CLI not found. Install + authenticate the Google "
            "Cloud SDK (gcloud auth login).",
            file=sys.stderr,
        )
        return 2

    project = args.project or datastore.Client().project
    exclude = {k for k in args.exclude.split(",") if k}
    explicit = [k for k in args.kinds.split(",") if k]
    kinds = explicit if explicit else enumerate_kinds(exclude)
    kinds = [k for k in kinds if k not in exclude]  # excludes always win
    if not kinds:
        print("error: no kinds to copy after applying --exclude.", file=sys.stderr)
        return 2

    # PIN gate — this reads the LIVE database. No TTY → run_pin_challenge raises.
    run_pin_challenge(
        context_lines=[
            f"project = {project}",
            f"source  = {args.source_database}  (LIVE)  [READ-ONLY]",
            f"target  = {args.target_database}  (default namespace)",
            f"bucket  = {args.bucket}",
            f"kinds   = {', '.join(kinds)}",
            "managed export of LIVE data to GCS, then import into the test DB.",
        ],
    )

    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    export_uri = f"{args.bucket.rstrip('/')}/{timestamp}"
    collection_flag = "--collection-ids=" + ",".join(kinds)
    namespace_flags = (
        [f"--namespace-ids={args.namespace_ids}"] if args.namespace_ids is not None else []
    )
    project_flag = f"--project={project}"

    print(f"\n[1/2] exporting {args.source_database} → {export_uri} ...")
    output_prefix = _run_gcloud(
        [
            "firestore", "export", export_uri,
            f"--database={args.source_database}", project_flag,
            collection_flag, *namespace_flags,
            "--format=value(response.outputUriPrefix)",
        ],
        capture=True,
    ) or export_uri  # fall back to the prefix we passed if gcloud printed nothing

    print(f"\n[2/2] importing {output_prefix} → {args.target_database} ...")
    _run_gcloud([
        "firestore", "import", output_prefix,
        f"--database={args.target_database}", project_flag,
        collection_flag, *namespace_flags,
    ])

    print(
        f"\n✓ done — {args.target_database} seeded from {args.source_database} "
        f"({len(kinds)} kinds). Boot the dev server against {args.target_database}."
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PinChallengeError as exc:
        sys.exit(f"dev-mirror import aborted: {exc}")
    except subprocess.CalledProcessError as exc:
        sys.exit(f"dev-mirror import failed: gcloud exited {exc.returncode}")
