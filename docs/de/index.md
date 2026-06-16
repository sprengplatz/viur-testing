# viur-testing

Sicherer Test-Modus für ViUR-core-Projekte – primär für
Playwright-End-to-End-Tests.

## Warum viur-testing?

`viur-testing` schaltet den laufenden viur-core-Prozess auf eine
dedizierte **benannte Datastore-Datenbank** um (Standard: `viur-tests`)
und verweigert jeder Anfrage den Zugriff auf ein Modul, solange der
Aufrufer nicht nachweisen kann, dass er bewusst mit der Test-Instanz
sprechen wollte. Abgesichert wird das durch mehrere ineinandergreifende
[Sicherheitsmechanismen](#sicherheitsmechanismen).

## Inhalt

Das Projekt besteht aus einem PyPI-Package
([spltz-viur-testing](https://pypi.org/project/spltz-viur-testing)) und
einem npm-Package
([`@spltz/viur-testing`](https://www.npmjs.com/package/@spltz/viur-testing)).
Das PyPI-Package stellt die Backend-Erweiterung bereit, das npm-Package
die Playwright-API sowie einen Stub-Generator.

**Python-Package:**

- ViUR-3-core-Patches für Multi-Datastore- und Namespace-Support.
- Request-Validator zur Header-Prüfung.
- `viur-mirror`-Tool zum Kopieren von Daten in eine
  Namespace-Datastore-Instanz.
- PIN-Bestätigung vor dem Start.

**npm-Package:**

- Header-Injection für Vite-Anwendungen.
- PIN-Bestätigung vor dem Start.
- Playwright-Patches zum Erzwingen der Sicherheitsmechanismen.
- `init`-Tool zum Erzeugen eines Stubs.

## Sicherheitsmechanismen

1. **`activate()` verweigert den Dienst außerhalb von
   `conf.instance.is_dev_server`** – kein Test-Modus auf einer
   produktiven Instanz.
2. **DB-Roundtrip** – ein Schreib-Lese-Zyklus gegen die Zieldatenbank
   verifiziert den erfolgreichen Client-Wechsel, bevor der Start
   fortgesetzt wird.
3. **`TestModule` und `ConfigModule`** verweigern die Instanziierung
   außerhalb des Dev-Servers oder ohne vorheriges `activate()`.
4. **Test-API außerhalb von `deploy/`** – die projektspezifischen
   Test-Module liegen außerhalb des Deploy-Ordners und werden damit nie
   in die Produktion ausgeliefert.
5. **Pro-Anfrage-Token `X-Viur-Test-Token`** – jede Anfrage muss den
   ausgehandelten Token mitführen, sonst wird sie abgewiesen.
6. **Runner-Preflight** – `require_test_mode()` ruft
   `/_test/config/status` auf und verweigert den Teststart, wenn der
   Server eine andere Datenbank, Projekt-ID oder einen anderen
   Token-Hash meldet als erwartet.
7. **`protect()`** – schützt Live-Instanzen vor versehentlichen Anfragen,
   die den Testing-Header tragen.

## Endpunkte

- `POST /_test/config/status` – stellt den Session-Token in der
  Test-Datenbank bereit (oder gibt ihn zurück), verifiziert erneut
  Dev-Server + Datenbank und liefert JSON `{test_mode, is_dev_server,
  database, project_id, token, token_hash, version}`. Nur per POST, um
  Drive-by-GETs aus parallelen Browser-Tabs zu blockieren.
- `POST /_test/config/finish` – löscht die Token-Entity aus der
  Test-Datenbank und beendet damit die Session.

Beide werden vom [`ConfigModule`](api/config.md) innerhalb des
[`TestModule`](api/test.md)-Containers bereitgestellt. Test-Suiten
hängen als zusätzliche Submodule unter demselben `/_test/`-Schirm.

## Minimalbeispiel

Zwei Einzeiler im Host. `main.py`:

```python
import viur.testing
viur.testing.setup()

from viur.core import setup as core_setup
import modules, render
app = core_setup(modules, render)
```

`modules/__init__.py`:

```python
import viur.testing
viur.testing.register_modules(globals())
```

Runner-seitig:

```python
from viur.testing import require_test_mode, finish

status = require_test_mode("http://localhost:8080")
try:
    # run tests, sending X-Viur-Test-Token: status.token
    ...
finally:
    finish("http://localhost:8080", status.token)
```

## Wie es weitergeht

- [Erste Schritte](getting-started.md) – schrittweise Verdrahtung von
  Host + Runner samt GCP-seitiger Vorbereitung (benannte
  Datastore-Datenbank).
- [Development-Modus](dev-mirror-mode.md) – lockere Variante, die die
  Entwicklung von Tests vereinfacht.
- [Guarded-Modus](guarded-mode.md) – Variante, die im begrenzten Rahmen
  gegen eine beliebige Datenbank (auch live) laufen kann.
- [Changelog](changelog.md).
