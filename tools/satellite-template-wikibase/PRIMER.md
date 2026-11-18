# PRIMER — {{slug}}

Arbeitsplan für `n4o-rse/{{slug}}`. Stand: {{today}} (Gerüst erzeugt mit `tools/new_satellite.py --wikibase` aus wikibase-static {{version}}).

Sprache: dieses Dokument ist deutsch, alles andere im Repo (Code, Kommentare, README) ist britisches Englisch.

## Beschlusslage

- Quelle: [{{host}}]({{source_url}}), gesichert mit `harvest` nach `data/raw/` (inkrementell, über `lastrevid`); Anubis wird nie umgangen (`--from-dir` ist der Ausweg).
- Eigene URIs: `rdf_base` ist die Pages-Adresse, Präfix `{{prefix}}`; nichts darf auf die Quell-Wikibase als Bezeichner verweisen.
- Technik wie `fuzzy-sl-static`, aber mit dem Stand von 0.29.0: Deploy über die Action (`deploy: true`), `docs/` und `data/derived/` werden nicht committet, `data/raw/` und `dist/` schon.
- Die Ids der Quelle bleiben (`Q…`, `P…`).

## Schritte

| Id | Schritt | Stand |
|---|---|---|
| S0 | Gerüst, erster Lauf (`harvest --probe`, `harvest`, `fetch-logo`, `--strict`), Push, Pages-Quelle = GitHub Actions | offen |
| S1 | `formatter_property` in `site.yaml` setzen (Property „formatter URL“ der Quelle suchen) | offen |
| S2 | `data/crm.csv` (CIDOC-CRM-Anker für die Klassen), danach `check-crm` | offen |
| S3 | Logo: Urheber und Lizenz in README und `site.yaml` nennen | offen |

## Offene Punkte

- Große Quelle (viele hundert Items): `entity_files: false` und `browser_graph: slim` in `site.yaml` (stehen als Kommentar dort).
- Aufnahme in `beaverbridge-registry` (Quellenliste) nach dem ersten grünen Lauf.
