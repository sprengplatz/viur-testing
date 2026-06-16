# Erste Schritte

Diese Seite beschreibt die minimale Einrichtung, um ein viur-core-Projekt in
einen sicheren, Playwright-tauglichen Test-Modus zu versetzen.

## Der Test-Modus

Der Test-Modus ist der sicherste Modus und der Standard: alle
Sicherheitsmechanismen sind aktiv. Er ist der einzige Modus, der ohne
PIN-Eingabe startet — und damit der einzige, der sich in CI/CD automatisiert
einsetzen lässt.

Einschränkung: Reguläre Requests, etwa aus dem Admin, werden abgewiesen, da sie
keinen gültigen `X-Viur-Test-Token` mitsenden.

## Voraussetzungen

- Python ≥ 3.12
- viur-core ≥ 3.7, < 4

## Die Test-Datenbank anlegen

Lege in der GCP-Console eine neue benannte Datastore-Datenbank im *selben
Projekt* wie deine Live-Datenbank an. Standardname: **`viur-tests`**. Ein
abweichender Name ist möglich und wird an `setup(database=…)` übergeben.

Daten müssen nicht migriert werden — die Startup-Tasks von viur-core befüllen
die Datenbank beim ersten Boot (initialer Admin-Benutzer, `viur-conf`-Entität
usw.).

## viur-testing installieren

Als **Laufzeit**-Abhängigkeit einbinden (das Paket wird auch in Produktion
importiert, um den `protect()`-Guard zu installieren). Mit pipenv:

```bash
pipenv install spltz-viur-testing
```

oder mit uv:

```bash
uv add spltz-viur-testing
uv sync
```

## `main.py` anpassen

```python
# main.py — viur.testing.setup() MUST be the first lines, before any
# ``from viur.core ...`` import.
import viur.testing
viur.testing.setup()

# Only now may viur.core be imported.
from viur.core import setup as core_setup
import modules, render

app = core_setup(modules, render)
```

`setup()` hängt sämtliche Patches und Validatoren ein und muss daher — noch vor
jedem `from viur.core …`-Import — als Allererstes aufgerufen werden.

## `modules/__init__.py` anpassen

```python
# modules/__init__.py — after your usual auto-discovery
import viur.testing
viur.testing.register_modules(globals())
```

`register_modules()` registriert das verschachtelte `TestModule` samt
`ConfigModule`, sodass die Endpunkte `_test/config/status` und
`_test/config/finish` verfügbar werden. In Produktion (ohne vorheriges
`activate()`) ist der Aufruf ein No-op.

## Den Dev-Server im Test-Modus starten

```bash
VIUR_TESTING=test viur run develop
```

Beim ersten Boot solltest du im Log sehen:

- den Startup-Task von viur-core, der einen Admin-Benutzer in `viur-tests`
  anlegt,
- eine neue `viur-conf`-Entität,
- eine neue `hmacKey`-Entität —

… alles in der **`viur-tests`**-Datenbank. Deine Live-Datenbank bleibt
unangetastet. Zusätzlich zeigt das Boot-Banner die Datenbank- und
Namespace-Informationen an.

## Die Playwright-Suite scaffolden

Das begleitende npm-Paket
[`@spltz/viur-testing`](https://www.npmjs.com/package/@spltz/viur-testing)
liefert einen One-Shot-Scaffolder mit:

```sh
npx viur-testing-init
```

Der Scaffolder erzeugt immer eine **Test-Modus**-Suite. Ohne Pfadargument läuft
er die Verzeichnisstruktur nach oben, bis er den `deploy/`-Ordner findet, und
schlägt `<root>/testing/e2e` als Ziel vor — der Pfad lässt sich vor dem
Schreiben bestätigen oder anpassen. Bereits vorhandene Dateien werden bei
erneutem Lauf übersprungen.

## Die Suite installieren und booten

Im gescaffoldeten Verzeichnis:

```sh
cd testing/e2e
npm install
npx playwright install --with-deps chromium
```

Die generierte `playwright.config.ts` ruft `createGlobalSetup()` (aus
`@spltz/viur-testing`) auf, das:

- `POST /json/_test/config/status` gegen `E2E_BACKEND_URL` probt,
- bei **HTTP 200** den bilateralen Handshake validiert (`test_mode`,
  `is_dev_server`, `database`, `project_id`; der SHA-256-`token_hash` stimmt mit
  dem zurückgegebenen Token überein) und das Session-Token nach
  `.auth/token.json` schreibt, damit die Worker-Fixtures es aufgreifen,
- bei **HTTP 404** in den Guarded-Modus wechselt (interaktives PIN-Gate),
- bei allem anderen (5xx, fehlerhaftes JSON, Integritätsfehler) den Lauf
  abbricht — keine stillen Downgrades.

Führe die Suite gegen dein lokales, im Test-Modus scharfgeschaltetes Backend
aus:

```sh
npm test
```
