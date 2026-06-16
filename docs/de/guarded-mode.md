# Guarded-Modus

Der Guarded-Modus ist eine Browsing-Variante zum Testen gegen Live-Daten. Das
ist riskant und sollte nur mit gutem Grund von Entwicklern genutzt werden, die
wissen, was ihre Tests mit dem System anstellen. Im Backend ist kein
Schutzmechanismus aktiv; entsprechend sind auch die `_test/`-Endpunkte nicht
verfügbar. Als Ausgleich erzwingt der Playwright-Runner vor dem Start eine
PIN-Eingabe – als bewusste Bestätigung und um den Einsatz in CI/CD zu
verhindern.

Der Modus aktiviert sich automatisch, sobald das Backend nicht im Test-Modus
läuft – auch wenn das versehentlich passiert.

## Die PIN-Abfrage

Die Abfrage zeigt zur Kontrolle noch einmal die Ziel-URL an:

```
$ npx playwright test

[viur-testing] probing https://staging.example.com/json/_test/config/status ...

⚠  GUARDED MODE
   Target backend:  https://staging.example.com
   The backend is NOT in test mode. Tests will interact with
   the live application — no test database, no token guard,
   no _test/ fixture endpoints. Specs that use _test
   infrastructure are auto-skipped.

   Confirm by typing:   8 4 1 7 3 9

   > _
```

## Was sich innerhalb der Suite ändert

Tests, die `_test/`-Infrastruktur nutzen, werden übersprungen – als *skipped*,
nicht *failed*.

Ein Lauf-Report sieht so aus:

```
Running 12 tests using 1 worker

  ✓ tests/public-landing.spec.ts:8:3   › renders hero (340ms)
  ✓ tests/public-landing.spec.ts:14:3  › nav links work (220ms)
  -  tests/user-login.spec.ts:5:3      › uses _test infrastructure …
  -  tests/user-login.spec.ts:18:3     › uses _test infrastructure …
  ✓ tests/footer.spec.ts:6:3            › privacy link present (180ms)
  ...
```

## Den Modus zur Laufzeit erkennen

Wenn du innerhalb einer Spec oder eines Fixtures verzweigen musst (selten – die
meisten Specs sollten das nicht brauchen), prüfe `process.env.VIUR_TESTING_MODE`:

```ts
import { MODE_ENV_VAR } from "@spltz/viur-testing"

if (process.env[MODE_ENV_VAR] === "guarded") {
  // running against a live backend, no _test infrastructure
}
```
