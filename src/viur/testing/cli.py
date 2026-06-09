"""
Dev-Mirror — copy a live data slice into a per-developer test namespace.

Copies entities from the live ``(default)`` database (default namespace) into a
**named test database** (``viur-tests``) under a developer-chosen
**namespace**, so each developer gets an isolated data slice to test against.

The copy goes through the regular ``google.cloud.datastore`` client (which, as
of v2.x, can target both a named ``database`` and a ``namespace``), reading the
source **read-only** and writing entity-by-entity into the target namespace.

Key properties
--------------
- **Per-developer isolation.** The target ``--target-namespace`` is required;
  every run lands in exactly that namespace of the test database, so developers
  do not share or clobber each other's slice.
- **Keys remapped onto the target partition.** Each entity's own key is
  rebuilt in the target namespace, and every key-valued *property* (relations),
  recursively through lists and embedded entities, is rewritten onto the target
  partition too. This is mandatory: a copied entity in ``viur-tests`` may not
  reference keys in the source ``(default)`` database, so a literal verbatim
  copy is rejected by Datastore. Applying the target namespace as well means
  relations resolve within the copied slice.
- **Reads live production.** The source is opened through
  :class:`~viur.testing.mirror.ReadOnlyClient` so the copy can never mutate
  ``(default)`` — but it does read live data, hence the PIN gate.
- **Secrets stay out.** ``viur-conf`` (holds the hmacKey) and ``viur-session``
  are excluded by default, so secrets/sessions are never copied. The test
  database keeps its own ``viur-conf``/hmacKey from first boot.
- **Never writes into ``(default)``.** ``--target-database`` may never be the
  live database; this is a hard guard with no override.

Safety gate
-----------
A fresh 6-digit PIN (reused from :mod:`viur.testing.pin`) is required every
run — no TTY means no run. The prompt names the project, source and target
namespace so you see exactly what is about to be copied.

Requirements
------------
- Application-default credentials (``gcloud auth application-default login``).
- IAM roles to read ``(default)`` and write the test database.
- The target named database (``viur-tests``) must already exist.

Usage
-----
Once the package is installed it exposes the ``viur-mirror`` console script
(declared under ``[project.scripts]`` in ``pyproject.toml``)::

    viur-mirror --project my-gcp-project --target-namespace ak
    viur-mirror --project my-gcp-project --target-namespace ak --kinds user,page
    viur-mirror --project my-gcp-project --target-namespace ak --target-database viur-tests

From a source checkout (without installing the console script) the module is
runnable directly via the same :func:`run` entry point::

    uv run python -m viur.testing.cli --project my-gcp-project --target-namespace ak
"""

from __future__ import annotations

import argparse
import sys

from google.cloud import datastore

from viur.testing.constants import MIRROR_EXCLUDE_KINDS
from viur.testing.mirror import ReadOnlyClient
from viur.testing.pin import PinChallengeError, run_pin_challenge

# viur-core secret / per-instance kinds that must never be copied (verified
# against viur-core 3.x: hmacKey is a property on the "viur-conf" entity, so
# excluding that kind covers the secret; "viur-session" is Session.kindName).
DEFAULT_EXCLUDE = set(MIRROR_EXCLUDE_KINDS)

# The live database id. It is the copy SOURCE and must NEVER be the copy
# TARGET — seeding into "(default)" would overwrite production. This is a hard
# guard with no override flag.
PROTECTED_TARGET_DATABASE = "(default)"


def _database_arg(db_id: str) -> str:
    """Map the human-facing ``(default)`` alias to the value the datastore
    client expects for the default database: the **empty string**. The API
    rejects the literal ``"(default)"`` ("Please use the empty string to denote
    the (default) database."). ``""`` is returned unchanged."""
    return "" if db_id == PROTECTED_TARGET_DATABASE else db_id

# Datastore commits accept at most 500 mutations; batch puts up to this many.
PUT_BATCH_SIZE = 500


def enumerate_kinds(source, exclude: set[str]) -> list[str]:
    """Return the user-data kinds in *source* minus *exclude* and the reserved
    ``__*__`` metadata kinds. *source* is a (read-only) datastore client."""
    kinds: list[str] = []
    for meta in source.query(kind="__kind__").fetch():
        name = meta.key.name
        if not name or name.startswith("__") or name in exclude:
            continue
        kinds.append(name)
    return kinds


def _remap_value(value, target):
    """Rewrite every ``datastore.Key`` reachable in *value* onto *target*'s
    partition (project + database + namespace), recursing into lists, dicts and
    embedded entities. A copied entity in ``viur-tests`` may not reference keys
    in the source ``(default)`` database, so this is mandatory for any entity
    that carries key-valued properties (relations); the target namespace is
    applied too, so relations resolve within the copied slice."""
    if isinstance(value, datastore.Key):
        return target.key(*value.flat_path)
    if isinstance(value, datastore.Entity):  # subclass of dict — check first
        clone = datastore.Entity(
            key=target.key(*value.key.flat_path) if value.key is not None else None,
            exclude_from_indexes=tuple(value.exclude_from_indexes),
        )
        clone.update({k: _remap_value(v, target) for k, v in value.items()})
        return clone
    if isinstance(value, dict):
        return {k: _remap_value(v, target) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_remap_value(v, target) for v in value]
    return value


def copy_kind(source, target, kind: str, *, batch_size: int = PUT_BATCH_SIZE) -> int:
    """Copy every entity of *kind* from *source* into *target*, re-keying each
    entity's own key — and every key-valued property (relations), recursively —
    onto *target*'s partition. Returns the number of entities written."""
    copied = 0
    batch: list[datastore.Entity] = []
    for entity in source.query(kind=kind).fetch():
        clone = datastore.Entity(
            key=target.key(*entity.key.flat_path),
            exclude_from_indexes=tuple(entity.exclude_from_indexes),
        )
        clone.update({k: _remap_value(v, target) for k, v in entity.items()})
        batch.append(clone)
        if len(batch) >= batch_size:
            target.put_multi(batch)
            copied += len(batch)
            batch = []
    if batch:
        target.put_multi(batch)
        copied += len(batch)
    return copied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Copy a live (default) data slice into a test-DB namespace.",
    )
    parser.add_argument(
        "--target-namespace", required=True,
        help="namespace in the test database to copy INTO (per-developer slice)",
    )
    parser.add_argument("--source-database", default="(default)")
    parser.add_argument(
        "--source-namespace", default=None,
        help="source namespace to read from (default: the default namespace)",
    )
    parser.add_argument("--target-database", default="viur-tests")
    parser.add_argument(
        "--project", required=True,
        help="GCP project id (required — never inferred, this reads live data)",
    )
    parser.add_argument(
        "--kinds", default="",
        help="comma-separated kinds to copy; default = all kinds minus --exclude",
    )
    parser.add_argument(
        "--exclude", default=",".join(sorted(DEFAULT_EXCLUDE)),
        help="comma-separated kinds to never copy (secrets/sessions)",
    )
    args = parser.parse_args(argv)

    # Hard safety guard: never write INTO the live database. Both "(default)"
    # and the empty string denote it, so guard on the normalised value.
    if _database_arg(args.target_database) == "":
        print(
            f"error: refusing to seed into the live {PROTECTED_TARGET_DATABASE!r} "
            "database — --target-database must be a separate test database "
            "(e.g. viur-tests).",
            file=sys.stderr,
        )
        return 2

    project = args.project
    source_namespace = args.source_namespace or None
    source = ReadOnlyClient(datastore.Client(
        project=project,
        database=_database_arg(args.source_database),
        namespace=source_namespace,
    ))
    target = datastore.Client(
        project=project,
        database=_database_arg(args.target_database),
        namespace=args.target_namespace,
    )

    exclude = {k for k in args.exclude.split(",") if k}
    explicit = [k for k in args.kinds.split(",") if k]
    kinds = explicit if explicit else enumerate_kinds(source, exclude)
    kinds = [k for k in kinds if k not in exclude]  # excludes always win
    if not kinds:
        print("error: no kinds to copy after applying --exclude.", file=sys.stderr)
        return 2

    # PIN gate — this reads the LIVE database. No TTY → run_pin_challenge raises.
    run_pin_challenge(
        context_lines=[
            f"project = {project}",
            f"source  = {args.source_database} / ns={source_namespace or '(default)'}  (LIVE)  [READ-ONLY]",
            f"target  = {args.target_database} / ns={args.target_namespace}",
            f"kinds   = {', '.join(kinds)}",
            "copies LIVE data entity-by-entity into the test namespace.",
        ],
    )

    total = 0
    for kind in kinds:
        n = copy_kind(source, target, kind)
        print(f"  • {kind}: {n}")
        total += n

    print(
        f"\n✓ done — copied {total} entities ({len(kinds)} kinds) into "
        f"{args.target_database} / ns={args.target_namespace}. "
        f"Boot the dev server against that database + namespace."
    )
    return 0


def run(argv: list[str] | None = None) -> int | str:
    """Console-script entry point: run :func:`main` and translate the declined
    PIN gate into a process exit value.

    Returns the integer exit code on success/early-out, or an error string
    (which ``sys.exit`` prints to stderr before exiting ``1``) when the PIN
    gate is declined.
    """
    try:
        return main(argv)
    except PinChallengeError as exc:
        return f"dev-mirror copy aborted: {exc}"


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run())
