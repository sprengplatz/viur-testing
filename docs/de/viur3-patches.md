# ViUR3 Monkey-Patches

viur-testing betreibt einen ViUR3-/viur-core-Prozess gegen eine **benannte**
Datastore-Datenbank (Standard `viur-tests`) und einen optionalen **Namespace**.
Weder viur-core noch `google-cloud-datastore` unterstützen das vollständig out
of the box — der Test-Modus überbrückt das mit einer Reihe von
Laufzeit-Patches.

Alle Patches teilen zwei Eigenschaften:

- **Nur Dev-Server** — installiert über `activate()`; einzige Ausnahme ist der
  Production-Guard, den `protect()` in jeder Umgebung installiert.
- **Idempotent** — eine erneute Aktivierung (Test-Re-Entry) ersetzt den Wrapper,
  statt Schichten zu stapeln.

## 1. Datastore-Client-Tausch

**Ziel:** `viur.core.db.transport.__client__`

**Wofür:** viur-core bindet beim Import einen einzigen modulweiten
`datastore.Client()` an die Default-Datenbank. Der Test-Modus muss stattdessen
mit der benannten Test-Datenbank sprechen.

**Was er macht:** `activate()` baut einen
`datastore.Client(database=…, namespace=…)`, weist ihn per Schreib-Lese-Probe
nach und ersetzt `transport.__client__` damit — *vor* jedem weiteren
viur-core-Import, sodass alle späteren Verbraucher den getauschten Client sehen.
Deshalb muss `activate()` ganz oben in `main.py` laufen, bevor
`viur.core.db.transport` importiert wird.

## 2. Key-Factory — Datenbank & Namespace injizieren

**Ziel:** `viur.core.db.types.Key.__init__`

**Wofür:** viur-cores `Key` reicht nur `project=` an
`google.cloud.datastore.Key` weiter, nie `database=` oder `namespace=`. Gegen
einen Client mit benannter Datenbank scheitert dadurch jeder Aufruf mit
`InvalidArgument: 400 mismatched databases within request`. Beim Namespace
dasselbe Problem — Schreibvorgänge landen im Default-Namespace, während Lesungen
aus dem Test-Namespace kommen (still leere Ergebnisse).

**Was er macht:** umhüllt `Key.__init__` so, dass die Argumente `database` und
`namespace` standardmäßig auf die Werte des aktiven Clients gesetzt werden;
explizit übergebene Argumente gewinnen weiterhin. Das originale `__init__` wird
am Wrapper hinterlegt, sodass eine erneute Aktivierung zuerst auspackt und dann
neu umhüllt (kein Stapeln).

## 3. Legacy-urlsafe-Keys für benannte Datenbanken

**Ziel:** `google.cloud.datastore.key.Key.to_legacy_urlsafe`

**Wofür:** die Originalmethode wirft `ValueError("to_legacy_urlsafe only
supports the default database")` bei jedem Key mit gesetzter `database`.

**Was er macht:** umhüllt die Google-Methode so, dass `self._database` rund um
den Originalaufruf temporär geleert und im `finally` wiederhergestellt wird. Der
resultierende urlsafe-String trägt Projekt + Namespace + Pfad (die Datenbank-ID
entfällt) — im Test-Prozess unbedenklich, da jeder Key dieselbe Datenbank
adressiert, die der Key-Factory-Patch (#2) beim Parsen wieder einsetzt. Gepatcht
wird an der Wurzel (die Google-Methode) statt an viur-cores `__str__`, sodass es
viur-core-Änderungen übersteht und jede Aufrufstelle abdeckt.

## 4. Boot-Banner — die aktive Datenbank anzeigen

**Ziel:** `viur.core.setup`

**Wofür:** beim Hochfahren des Dev-Servers ist die wichtigste Information,
*welcher* Datastore mit dem Prozess verdrahtet ist (Prod-Default vs.
`viur-tests`).

**Was er macht:** umhüllt `viur.core.setup()` so, dass während der Ausführung
`builtins.print` temporär durch einen Sniffer ersetzt wird, der viur-cores
Banner `LOCAL DEVELOPMENT SERVER IS UP AND RUNNING` erkennt und direkt vor dem
Banner-Abschluss die Zeilen `database = …` (und `namespace = …`, falls gesetzt)
in passender Breite und Stilistik einfügt. Das originale `print` wird
wiederhergestellt, sobald `setup()` zurückkehrt — außerhalb des Banner-Fensters
bleibt also nichts betroffen. Breite und Abschlusszeile werden zur Laufzeit
erkannt, sodass eine künftige Banner-Änderung in viur-core sauber degradiert.

## 5. Request-Validatoren

**Ziel:** `viur.core.request.Router.requestValidators`

Zwei Validatoren werden an die klassenweite Liste des Routers angehängt:

- **`TokenValidator`** — installiert von `activate()` (Dev/Test). Weist jede
  Nicht-Bootstrap-Anfrage ab, der ein passendes `viur-test-token`-Cookie fehlt
  (konstantzeitiger Vergleich). Die Bootstrap-Pfade `/_test/config/status`,
  `/_test/config/enter` und `/_test/config/finish` umgehen ihn, damit Runner und
  manuelle Navigation eine Session öffnen können, bevor ein Cookie existiert.
- **`ProductionGuardValidator`** — installiert von `protect()` in **jeder**
  Umgebung; überwacht das `viur-test-token`-**Cookie** als Stolperdraht: Auf
  einem Nicht-Dev-Server beantwortet er jede Anfrage mit diesem Cookie mit 403,
  unabhängig vom Wert; in Dev ist er ein No-op (dort besitzt der
  `TokenValidator` das Cookie). Ein Test-Cookie darf Produktion nie erreichen,
  der Guard weist es also laut ab, statt es durchfallen zu lassen. Siehe
  [Validatoren](api/validator.md).

## 6. Closed-System-Allowlist

**Ziel:** `conf.security.closed_system_allowed_paths`

**Wofür:** viele Projekte laufen mit `conf.security.closed_system = True`, was
jede Anfrage mit nicht freigegebenem Pfad mit 401 beantwortet — noch vor dem
Routing. Der `/_test/`-Bootstrap und projektseitig registrierte
Fixture-Submodule wären selbst mit gültigem Token blockiert.

**Was er macht:** `activate()` erweitert die Liste um die Wildcards `_test/*`
und `*/_test/*` (deckt jedes Render-Präfix und registrierte Fixtures ab). Die
Zugriffskontrolle auf diesen Pfaden übernimmt weiterhin der `TokenValidator` —
die Allowlist bringt die Anfrage nur am Closed-System-Gate vorbei.
