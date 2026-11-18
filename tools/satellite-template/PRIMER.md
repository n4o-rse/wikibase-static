# PRIMER — {{slug}}

Arbeitsplan für `n4o-rse/{{slug}}`. Stand: {{today}} (Gerüst erzeugt mit `tools/new_satellite.py` aus wikibase-static {{version}}).

Sprache: dieses Dokument ist deutsch, alles andere im Repo (Code, Kommentare, README) ist britisches Englisch.

## Beschlusslage

- Items: {{seed_text}}
- Technik wie `wd-ogham-static`: `import-wikidata --generic --provenance item` (der Wrapper `main.py` setzt beides), `entity_files: {{entity_files}}`, `browser_graph: {{browser_graph}}`, Präfix `{{prefix}}`, Deploy über die Action (`deploy: true`).
- Eigene Ids `Q100` ff. und `P100` ff.; die Wikidata-Id steht als Zwilling `P4`.

## Schritte

| Id | Schritt | Stand |
|---|---|---|
| S0 | Gerüst, erster Lauf (`seeds-from-sparql`, `import-wikidata`, `--strict`), Push | offen |
| S2 | `data/crm.csv` (CIDOC-CRM-Anker für die Klassen), `--skip-property` für Rauschen | offen |
| S3 | Seeds prüfen: findet die Abfrage zu viel oder zu wenig? (`data/raw/wikidata-seeds/*.json`, `dist/wikidata-gaps.csv`) | offen |

## Offene Punkte

- `owl:sameAs` der `P4`-Zwillinge auf Wikidata (Paket, S14d).
- Fotos und Beispielabfragen (`queries.yaml`) für Vorträge.
