# Development

Zum Entwickeln gibt es weitere Tools:

1. `viur-mirror` kopiert die Live-`(default)`-Datenbank
   in einen Namespace von `viur-tests` (out-of-band, gelegentlich).
2. **Manuelles Browsen** — den Dev-Server booten und das
   Cookie einmal über `/_test/config/enter` scharfschalten; danach die
   Test-Instanz direkt browsen, harte Navigation inklusive.

Der Test-Token bleibt durchgehend **voll erzwungen** — manuelles Browsen
funktioniert, weil das `viur-test-token`-Cookie bei jedem Request mitfährt
(siehe [ViUR3 Monkey-Patches](viur3-patches.md)).

## Im eigenen Namespace booten

```sh
VIUR_TESTING=ak viur run develop
```

`VIUR_TESTING=<namespace>` bootet den Test-Modus in diesem Namespace (hier `ak`);
`VIUR_TESTING=1` nutzt den Default-Namespace. Jeder Entwickler wählt seinen
eigenen Namespace, damit die gespiegelten Scheiben isoliert bleiben. Auch CI/CD
sollte einen eigenen Namespace haben.

## Manuelles Browsen scharfschalten (das Cookie)

Einmal navigieren zu:

```
http://localhost:8080/json/_test/config/enter
```

Das Backend antwortet mit `Set-Cookie` (`SameSite=Strict; HttpOnly; Path=/`). Ab
dann browst du `http://localhost:8080/...` ganz normal — harte Navigation,
Reloads, server-gerenderte Seiten: das Cookie wird automatisch angehängt und der
Token bleibt erzwungen.

## Namespace befüllen — `viur-mirror`

Das `viur-mirror`-Script kopiert Kinds aus einer Datenbank in deinen
`viur-tests`-Namespace. Das Projekt muss dabei zwingend angegeben werden:

```sh
viur-mirror --project my-gcp-project --target-namespace ak
```

- Die `(default)`-Datenbank ist als **Ziel** hart ausgeschlossen, um ein
  Überschreiben der Live-Daten zu verhindern, und wird über einen
  **read-only**-Client gelesen.
- **viur-core-System-Kinds sind ausgeschlossen**: `viur-conf` (enthält den
  hmacKey), `viur-session`, `viur-securitykey`.
- Um Konflikte mit File-Uploads zu vermeiden, sind zusätzlich `viur-relations`,
  `file`, `file_rootNode` und `viur-blob-locks` ausgeschlossen.

Folge: Es werden nur Daten kopiert, keine Dateien. (Ein künftiges Update soll
auch Datei-Kopien erzeugen.)

!!! warning "Seeding liest Live-Produktionsdaten"
    Das Seeding liest die Live-`(default)`-Datenbank (read-only) und ist
    PIN-gesichert. Es kann personenbezogene Daten in die Test-Scheibe ziehen —
    prüfe die `--exclude`-Liste auf PII, bevor du es ausführst.
