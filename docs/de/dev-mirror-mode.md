# Development-Modus

Der Development-Modus ist eine abgeschwächte Variante des Test-Modus: Er lockert
die Backend-Regeln so weit, dass Requests den Test-Token überspringen dürfen
(tokenless browsing). So steht eine vollwertige Entwicklungsumgebung zur
Verfügung – inklusive Admin-Requests und normalem Browsing, die keinen Token
mitsenden.

Im Gegenzug greifen zusätzliche Schutzmaßnahmen im Backend:

- **PIN beim Start** – der Dev-Server lässt sich nur nach PIN-Bestätigung
  scharfschalten; das verhindert den Einsatz in CI/CD.
- **Namespace verpflichtend** – ohne gesetzten Namespace startet der Modus
  nicht. Er operiert ausschließlich in `viur-tests`, nie auf der
  Live-Datenbank.
- **Application-ID-Freigabe** – die GCP-Projekt-ID muss explizit für
  tokenless-Zugriff freigeschaltet sein.

## Application-ID freischalten und verwenden

Die Whitelist der tokenless-berechtigten GCP-Projekt-IDs steht im Code – so wird
sie im PR reviewt und driftet nicht in einem Dotfile:

```python
import viur.testing
viur.testing.setup(tokenless_app_ids=["my-project-id"])

from viur.core import setup as core_setup
import modules, render
app = core_setup(modules, render)
```

Boote anschließend im **Development-Modus** und richte den Server auf **deinen**
Namespace aus. Syntax: `VIUR_TESTING=dev:<ns>`

```sh
VIUR_TESTING=dev:ak viur run develop
```

Vor dem eigentlichen Boot schützt eine frische PIN das Scharfschalten. Sobald
scharfgeschaltet, dürfen Requests den `X-Viur-Test-Token`-Header weglassen — du
kannst die App also direkt im Browser öffnen.

## Datenbank spiegeln

Das `viur-mirror`-Script kopiert Kinds aus einer Datenbank in deinen
`viur-tests`-Namespace. Das Projekt muss dabei zwingend angegeben werden:

```sh
viur-mirror --project my-gcp-project --target-namespace ak
```

- Die `(default)`-Datenbank ist als **Ziel** hart ausgeschlossen, um ein
  Überschreiben der Live-Daten zu verhindern.
- **viur-core-System-Kinds sind ausgeschlossen**: `viur-conf` (enthält den
  hmacKey), `viur-session`, `viur-securitykey`.
- Um Konflikte mit File-Uploads zu vermeiden, sind zusätzlich `viur-relations`,
  `file`, `file_rootNode` und `viur-blob-locks` ausgeschlossen.

Folge: Es werden nur Daten kopiert, keine Dateien. (Ein künftiges Update soll
auch Datei-Kopien erzeugen.)
