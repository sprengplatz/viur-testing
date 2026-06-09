"""Unit tests for :mod:`viur.testing.cli` — the dev-mirror copy entry point.

The datastore is faked: the source client serves canned ``__kind__`` metadata
and entities, the target client records ``put_multi`` batches. The PIN gate is
monkeypatched to pass, so these tests never hit GCP and never block on a TTY.
"""

import types

import pytest
from google.cloud import datastore

from viur.testing import cli
from viur.testing.pin import PinChallengeError


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _Meta:
    """A ``__kind__`` metadata row: only ``.key.name`` is read."""

    def __init__(self, name):
        self.key = types.SimpleNamespace(name=name)


class _FakeQuery:
    def __init__(self, items):
        self._items = items

    def fetch(self, limit=None):
        return list(self._items)


def _entity(kind, id_, props, *, project="proj-x", namespace=None):
    """Build a real datastore.Entity in the source namespace."""
    ent = datastore.Entity(key=datastore.Key(kind, id_, project=project, namespace=namespace))
    ent.update(props)
    return ent


class _FakeSourceClient:
    """Serves ``__kind__`` rows and per-kind entities; read through
    :class:`ReadOnlyClient` by the code under test."""

    def __init__(self, *, project="proj-x", kind_names=(), entities_by_kind=None):
        self.project = project
        self._kind_names = list(kind_names)
        self._entities = entities_by_kind or {}

    def query(self, *, kind):
        if kind == "__kind__":
            return _FakeQuery([_Meta(n) for n in self._kind_names])
        return _FakeQuery(self._entities.get(kind, []))


class _FakeTargetClient:
    """Records every ``put_multi`` batch and rebuilds keys in its namespace."""

    def __init__(self, *, project="proj-x", database="viur-tests", namespace="dev-x"):
        self.project = project
        self.database = database
        self.namespace = namespace
        self.batches: list[list] = []

    def key(self, *flat_path):
        return datastore.Key(*flat_path, project=self.project, namespace=self.namespace)

    def put_multi(self, entities):
        self.batches.append(list(entities))

    @property
    def written(self):
        return [e for batch in self.batches for e in batch]


@pytest.fixture
def patch_env(monkeypatch):
    """Wire up the happy-path doubles; return (source, target) handles.

    ``datastore.Client`` is dispatched by the ``database`` kwarg: the source
    database yields the source fake, anything else the target fake. The PIN
    gate is replaced with a pass-through.
    """
    def _apply(*, source=None, target=None):
        source = source or _FakeSourceClient()
        target = target or _FakeTargetClient()

        # main() normalises the default database to the empty string, so the
        # source client is requested with database="" and the target with its
        # named id.
        def _client(*, project=None, database=None, namespace=None, **_kw):
            return source if database == "" else target

        monkeypatch.setattr(cli.datastore, "Client", _client)
        monkeypatch.setattr(cli, "run_pin_challenge", lambda **_kw: None)
        return source, target

    return _apply


# ---------------------------------------------------------------------------
# enumerate_kinds
# ---------------------------------------------------------------------------


def test_enumerate_kinds_filters_meta_excluded_and_empty():
    source = _FakeSourceClient(
        kind_names=["user", "__Stat_Total__", "", "viur-conf", "page"],
    )
    assert cli.enumerate_kinds(source, {"viur-conf"}) == ["user", "page"]


# ---------------------------------------------------------------------------
# copy_kind
# ---------------------------------------------------------------------------


def test_copy_kind_rekeys_into_target_namespace_and_batches():
    source = _FakeSourceClient(entities_by_kind={
        "user": [_entity("user", i, {"n": i}, namespace=None) for i in (1, 2, 3)],
    })
    target = _FakeTargetClient(namespace="dev-x")

    # batch_size=2 → one full batch of 2, then a final batch of 1.
    n = cli.copy_kind(source, target, "user", batch_size=2)

    assert n == 3
    assert [len(b) for b in target.batches] == [2, 1]
    # every written entity's own key is now in the target namespace, value kept.
    for ent in target.written:
        assert ent.key.namespace == "dev-x"
    assert {dict(e)["n"] for e in target.written} == {1, 2, 3}


def test_copy_kind_empty_writes_nothing():
    source = _FakeSourceClient(entities_by_kind={"user": []})
    target = _FakeTargetClient()
    assert cli.copy_kind(source, target, "user") == 0
    assert target.batches == []


def test_copy_kind_remaps_relation_keys_into_target_namespace():
    rel = datastore.Key("other", 9, project="proj-x", namespace=None)  # source ns
    ent = _entity("user", 1, {"friend": rel}, namespace=None)
    source = _FakeSourceClient(entities_by_kind={"user": [ent]})
    target = _FakeTargetClient(namespace="dev-x")

    cli.copy_kind(source, target, "user")
    written = target.written[0]
    assert written.key.namespace == "dev-x"
    assert written["friend"].namespace == "dev-x"  # relation re-pointed into slice


# ---------------------------------------------------------------------------
# _remap_value
# ---------------------------------------------------------------------------


def test_remap_value_rewrites_keys_recursively():
    target = _FakeTargetClient(namespace="dev-x")
    src_key = datastore.Key("other", 2, project="proj-x", namespace=None)

    # bare key
    assert cli._remap_value(src_key, target).namespace == "dev-x"

    # list of keys
    out = cli._remap_value([src_key, src_key], target)
    assert [k.namespace for k in out] == ["dev-x", "dev-x"]

    # tuple of keys → returned as list
    out = cli._remap_value((src_key,), target)
    assert isinstance(out, list) and out[0].namespace == "dev-x"

    # dict with a nested key and a scalar
    out = cli._remap_value({"ref": src_key, "n": 5}, target)
    assert out["ref"].namespace == "dev-x" and out["n"] == 5

    # embedded entity WITH its own key and a key property
    emb = datastore.Entity(key=datastore.Key("sub", 3, project="proj-x", namespace=None))
    emb["ref"] = src_key
    out = cli._remap_value(emb, target)
    assert out.key.namespace == "dev-x"
    assert out["ref"].namespace == "dev-x"

    # embedded entity WITHOUT a key
    emb2 = datastore.Entity()
    emb2["ref"] = src_key
    out2 = cli._remap_value(emb2, target)
    assert out2.key is None
    assert out2["ref"].namespace == "dev-x"

    # scalar passthrough
    assert cli._remap_value("plain", target) == "plain"


# ---------------------------------------------------------------------------
# main — guards
# ---------------------------------------------------------------------------


def test_main_refuses_seeding_into_live_default_database(patch_env, capsys):
    source, target = patch_env()
    rc = cli.main([
        "--project", "proj-x", "--target-namespace", "dev-x",
        "--target-database", "(default)",
    ])
    assert rc == 2
    assert "refusing to seed into the live '(default)'" in capsys.readouterr().err
    assert target.batches == []  # guard fires before any copy


def test_main_aborts_when_no_kinds_left_after_exclude(patch_env, capsys):
    patch_env()
    # explicit --kinds, but every entry is also excluded → excludes win.
    rc = cli.main(["--project", "proj-x", "--target-namespace", "dev-x", "--kinds", "viur-conf"])
    assert rc == 2
    assert "no kinds to copy" in capsys.readouterr().err


def test_main_requires_target_namespace():
    with pytest.raises(SystemExit):
        cli.main(["--project", "proj-x"])  # argparse: --target-namespace is required


def test_main_requires_project():
    with pytest.raises(SystemExit):
        cli.main(["--target-namespace", "dev-x"])  # argparse: --project is required


# ---------------------------------------------------------------------------
# main — happy paths
# ---------------------------------------------------------------------------


def test_main_happy_explicit_kinds(patch_env, capsys):
    source = _FakeSourceClient(entities_by_kind={
        "user": [_entity("user", 1, {"n": 1})],
        "page": [_entity("page", 2, {"t": "x"}), _entity("page", 3, {"t": "y"})],
    })
    target = _FakeTargetClient(namespace="dev-andreas")
    patch_env(source=source, target=target)

    rc = cli.main([
        "--project", "proj-x",
        "--target-namespace", "dev-andreas",
        "--kinds", "user,page",
    ])
    assert rc == 0
    assert len(target.written) == 3
    assert all(e.key.namespace == "dev-andreas" for e in target.written)

    out = capsys.readouterr().out
    assert "user: 1" in out and "page: 2" in out
    assert "copied 3 entities (2 kinds)" in out


def test_main_happy_enumerated_kinds_excludes_secrets(patch_env):
    # No --kinds → enumerate; default exclude drops viur-conf/viur-session.
    source = _FakeSourceClient(
        kind_names=["user", "__Stat__", "", "viur-conf", "page"],
        entities_by_kind={
            "user": [_entity("user", 1, {})],
            "page": [_entity("page", 2, {})],
            "viur-conf": [_entity("viur-conf", "viur-conf", {"hmacKey": "secret"})],
        },
    )
    target = _FakeTargetClient(namespace="dev-x")
    patch_env(source=source, target=target)

    rc = cli.main(["--project", "proj-x", "--target-namespace", "dev-x"])
    assert rc == 0
    # only user + page copied; the secret kind was never touched.
    assert {e.key.kind for e in target.written} == {"user", "page"}


def test_main_passes_source_namespace_through(monkeypatch):
    captured = {}

    def _client(*, project=None, database=None, namespace=None, **_kw):
        captured.setdefault("projects", []).append(project)
        if database == "":  # default database (normalised from "(default)")
            captured["source_ns"] = namespace
            return _FakeSourceClient(entities_by_kind={"user": [_entity("user", 1, {})]})
        captured["target_ns"] = namespace
        return _FakeTargetClient(namespace=namespace)

    monkeypatch.setattr(cli.datastore, "Client", _client)
    monkeypatch.setattr(cli, "run_pin_challenge", lambda **_kw: None)

    rc = cli.main([
        "--project", "proj-x",
        "--target-namespace", "dev-x",
        "--source-namespace", "tenant-a",
        "--kinds", "user",
    ])
    assert rc == 0
    assert captured["source_ns"] == "tenant-a"
    assert captured["target_ns"] == "dev-x"
    # the explicit --project is passed to both clients (never inferred).
    assert captured["projects"] == ["proj-x", "proj-x"]


def test_main_normalises_default_database_to_empty_string(monkeypatch):
    """Regression: the datastore client rejects the literal "(default)" and
    requires the empty string for the default database."""
    seen = {}

    def _client(*, project=None, database=None, namespace=None, **_kw):
        if database == "":
            seen["source_db"] = database
            return _FakeSourceClient(entities_by_kind={"user": [_entity("user", 1, {})]})
        seen["target_db"] = database
        return _FakeTargetClient(namespace=namespace)

    monkeypatch.setattr(cli.datastore, "Client", _client)
    monkeypatch.setattr(cli, "run_pin_challenge", lambda **_kw: None)

    # default --source-database "(default)" must reach the client as "".
    rc = cli.main(["--project", "proj-x", "--target-namespace", "dev-x", "--kinds", "user"])
    assert rc == 0
    assert seen["source_db"] == ""           # never the literal "(default)"
    assert seen["target_db"] == "viur-tests"


def test_database_arg_maps_default_alias_to_empty_string():
    assert cli._database_arg("(default)") == ""
    assert cli._database_arg("") == ""
    assert cli._database_arg("viur-tests") == "viur-tests"


# ---------------------------------------------------------------------------
# run — entry-point wrapper
# ---------------------------------------------------------------------------


def test_run_returns_main_exit_code(monkeypatch):
    monkeypatch.setattr(cli, "main", lambda argv=None: 0)
    assert cli.run(["--target-namespace", "dev-x"]) == 0


def test_run_translates_pin_abort_to_message(monkeypatch):
    def _raise(argv=None):
        raise PinChallengeError("PIN confirmation failed.")

    monkeypatch.setattr(cli, "main", _raise)
    msg = cli.run([])
    assert isinstance(msg, str)
    assert msg.startswith("dev-mirror copy aborted:")
