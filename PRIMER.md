# PRIMER — wikibase-static

Arbeitsplan für `n4o-rse/wikibase-static`. Wird zu Beginn jedes Chats hochgeladen (Bundle, siehe A5) und am Ende zurückgeschrieben. Stand: 2026-10-21 (nach S6b, dem Abfrage-Editor; S7 als Konzept beschlossen, in S7a bis S7g geteilt, noch kein Code).

Sprache: dieses Dokument ist deutsch, alles andere im Repo (Code, Kommentare, README) ist britisches Englisch.

---

## Teil A — Immer gültig

### A1 Ausgangslage

**Ziel in einem Satz:** Eine bestehende Wikibase (z. B. Wikibase Cloud) per API sichern oder eine Dummy-Wikibase aus CSV aufbauen und beides als statische, read-only Seite auf GitHub Pages veröffentlichen, die wie eine Wikibase aussieht und sich so bedienen lässt (Q-/P-IDs anklicken, externe Links im neuen Tab), mit Suche, Karte und SPARQL-Seite im Browser.

| Repo | Rolle | Status |
|---|---|---|
| `n4o-rse/wikibase-static` | Paket, Orchestrator `main.py`, alle Schritte (dieses Repo) | neu, S1 |
| `n4o-rse/wikibase-static-template` | GitHub-Template-Repo: `site.yaml`, Pages-Workflow, installiert `wikibase-static` per pip | geplant, S9 |
| `n4o-rse/fuzzy-sl-static` | Demo 1: Rettung von `fuzzy-sl.wikibase.cloud` | angelegt 2026-10-20: `data/raw/` gefüllt (S4), dünnes Gerüst mit `main.py`-Wrapper; mit S3 kommen `site.yaml` und `docs/` (`python main.py build`); der Wrapper kennt `--strict` und den Schritt `load` und der Workflow-Aufrufer `.github/workflows/site.yml` sind eingecheckt (S8); die Seite ist live unter `https://n4o-rse.github.io/fuzzy-sl-static/` (Pages-Quelle „GitHub Actions“, 2026-10-21); mit S5 trägt jede Seite das Suchfeld (`docs/assets/search.js`, `search-index.js`) und der Seitenfuß nennt Paketversion 0.3.1; mit S6 kommen `dist/fuzzy-sl.wikibase.cloud.ttl`, `docs/sparql.html`, `docs/ttl/`, `docs/json/`, `docs/downloads/` und `pages_url` in `site.yaml`, mit S6b `docs/query.html`; der Orchestrator im Paket kommt mit S9 |
| `n4o-rse/chublets-wikibase-demo` | Demo 2: Dummy-Wikibase aus CSV (Ideen von chublets.software, `open-archaeo/py`) | geplant, S7b (Repo noch anzulegen, Florian legt es an; Gerüst kommt als Patch-ZIP) |
| `n4o-rse/wikibase-federation` | Schreibweg in eine echte Wikibase (`wbqs`, Action API, föderierte Werte); ab S7g kommt dort ein Push aus `data/derived/` dazu | besteht; Usecase `chublets` neu, S7g |
| `https://chublets-wikibase.de` | Ziel der echten Wikibase mit Federation; leer oder frisch (Florian 2026-10-21) | besteht; Zustand für mich ungeprüft |

Was schon existiert und **kopiert** wird (nicht referenziert, siehe A3):

| Quelle | Inhalt | Verwendung hier |
|---|---|---|
| `wikibase-federation` → `wbqs/client.py` | HTTP-Session, Retries nur bei GET, `Retry-After`, `maxlag`, User-Agent | nur der lesende Teil, für S4 |
| `open-archaeo` → `py/wikidata/preview.py` | rendert Statements als Wikidata-artige Seite (Property links, Wert rechts, Qualifier eingerückt, Source-Chips) | Vorlage für S3; die Eingabe dort ist ein eigenes Claim-Modell, kein Wikibase-JSON |
| `open-archaeo` → `py/wikidata/api.py` | `wbgetentities` lesend, nur `urllib` | Vorlage für S4 |
| `open-archaeo` → `py/wikidata/labels.py` | Label-Cache für Q-IDs außerhalb der Daten, gefüllt aus Wikidata | in S2 nur das Prinzip übernommen (eine fehlende ID wird als sie selbst angezeigt, nichts wird erfunden); der Code nicht, denn er holt Labels aus dem Netz (A3) |
| `open-archaeo` → `py/wikidata/sparql.py`, `queries.py`, `docs/sparql.html` | Query-Seite, Beispielqueries als Quelltext | Vorlage für S6; läuft dort gegen den Query Service, hier muss sie lokal laufen (Muster `wdt-sparql`) |

**Befunde** (geprüft 2026-10-20, per `git clone` der drei Repos und Lesen des Codes):

1. `wikibase-federation` ist ein **Schreib**-Werkzeug (QuickStatements-artiger Importer, `wbqs/importer.py`, `client.py`). Es enthält keinen Harvester.
2. In `open-archaeo/py` findet die Suche nach `harvest|wbgetentities|EntityData|allpages|Special:` nur `wbgetentities` in `py/wikidata/api.py` (lesend, gegen Wikidata). Pyodide, Leaflet und rdflib kommen in den `.py`-Dateien nicht vor. `docs/preview.html` (5 878 Zeilen) und `docs/sparql.html` wurden nicht geöffnet.
3. `bb-5kbc-sites` enthält keinen Wikibase-Harvester, nur Anreicherung gegen den Wikidata Query Service (`data/enrichment/mapping_admin_regions/wikidata_map.py`) mit User-Agent, Retries und `REQUEST_DELAY`.
4. Ein automatisierter Abruf der Startseite von `https://fuzzy-sl.wikibase.cloud` liefert die **Anubis**-Challenge (Proof-of-Work, benötigt JavaScript) statt der Seite. Ob `api.php` und `Special:EntityData` ebenfalls geschützt sind, war **ungeprüft**; **korrigiert 2026-10-20 (Befund 7): `api.php` ist für den Harvest erreichbar.**
5. Annahme, ungeprüft: Auf Wikibase Cloud liegen Items in Namespace 120 und Properties in 122. Der Harvest liest das in S4 per `meta=siteinfo` und verdrahtet es nicht fest. **Bestätigt 2026-10-20** (Befund 7).
6. Die Sandbox, in der der Harvest entwickelt wurde, erreicht `fuzzy-sl.wikibase.cloud` nicht (Proxy antwortet mit 403 auf den Tunnel, geprüft 2026-10-20). Wie sich Anubis gegenüber `api.php` verhält, war damit **ungeprüft**; der Lauf bei dir lokal hat es geklärt (Befund 7).
7. **Erster echter Harvest** (`fuzzy-sl-static`, Commit `bc288a2`, geprüft 2026-10-20 am Klon): `data/raw/` enthält 173 Entitäten (137 Items, 36 Properties), Manifest und Dateien stimmen überein (173 Zeilen, 0 SHA-256-Abweichungen). Die Quelle ist `https://fuzzy-sl.wikibase.cloud/w/api.php` (MediaWiki 1.43.11), Namespaces 120 (Item) und 122 (Property), jüngste Änderung 2025-11-01. Die Seitentitel tragen die Präfixe `Item:` und `Property:`, die ID wird also wie vorgesehen hinter dem Doppelpunkt gelesen. ID-Lücken: Items Q8, Q9, Q12, Q40, Q41, Q43, Q44, Q45, Q47, Q48, Q65 und Property P36 (nicht gelistet, vermutlich gelöscht; ob es Weiterleitungen sind, ist nicht geprüft).
   Inhalt, relevant für S2/S3/S5/S6: 488 Statements (464 `normal`, 24 `preferred`, alle mit `snaktype` `value`), 41 davon mit References, 0 Sitelinks. Haupt-Datentypen: Item 293, URL 79, Koordinate 62, String 51, External-ID 3; in Qualifiern zusätzlich Item 370, String 155, URL 62, Monolingual Text 2. **Nicht vorhanden:** Zeit, Quantity, Commons-Datei (also kein P18-Bild), föderierte Entitäten (alle Item-Verweise sind Q-/P-IDs). Labels fast nur Englisch (173 `en`, 2 `de`: Q82, Q130), 167 Entitäten mit Description, 21 mit Aliasen. Alle 62 Koordinaten haben als Globus `http://www.wikidata.org/entity/Q2` (Erde) und Genauigkeiten von 1e-6 bis 1e-4 Grad. Gesamtgröße der Rohdaten etwa 650 KB. Häufigste Properties: P1 (instance of) 134, P10 65, P4 62, P3 58.
   Datenqualität: URL-Werte wie `http://openopenstreetmap.org/node/…` (doppeltes „open“) und `http://wikidata.org/entity/Q6681` (ohne `www`) fallen auf; der Renderer sollte URLs unverändert zeigen und nicht „reparieren“.
8. `pip install wikibase-static` installiert nur das Paket unter `py/wikibase_static/`, nicht das `main.py` im Wurzelverzeichnis dieses Repos (geprüft 2026-10-20 mit Installation von GitHub in eine neue virtuelle Umgebung). Das Demo-Repo `fuzzy-sl-static` startet die Schritte deshalb über einen eigenen kleinen Wrapper (`python -m wikibase_static.step_<name>`). Für S9 gehört der Orchestrator ins Paket, sonst gibt es ihn doppelt.
9. Der Harvest schreibt die Schlüssel von `data/raw/entities/*.json` sortiert (nötig für byte-gleiche Läufe). Dadurch ist die Reihenfolge der Properties in `claims` aus der Quelle nicht mehr erhalten (`P1`, `P10`, `P11`, … statt der Reihenfolge der Wikibase); Listen wie `qualifiers-order` und `snaks-order` bleiben erhalten (geprüft 2026-10-20 am Loader). Der Loader ordnet Statements deshalb nach numerischer Property-ID.

10. **Formatter-URL bei `fuzzy-sl`** (geprüft 2026-10-20 am Klon): Sie liegt nicht in Wikidatas P1630, sondern in der lokalen Property P18 („Formatter URL“, Datentyp String) an den External-ID-Properties: P19 (`https://wikibase.semantic-kompakkt.de/entity/$1`) und P34 (`http://www.wikidata.org/entity/$1`); P21 (ISO 639-1) hat keine. Drei External-ID-Werte (Q131: P19; Q74: P19 und P34). Der Renderer liest die Formatter-Property deshalb aus `site.yaml` (`formatter_property`, Standard P1630).
11. Das npm-Paket `leaflet@1.9.4` bringt `LICENSE` und `dist/leaflet.css` mit **CRLF** (26 bzw. 661 Zeilen); `leaflet.js` hat LF (geprüft 2026-10-20). Beide Textdateien wurden beim Einchecken in `static/vendor/leaflet/` auf LF gebracht, sonst widersprechen sie der LF-Regel (A3). Die PNG-Bilder bleiben unverändert.
12. Q131 hat zwei identische Koordinaten-Statements (gleiche Breite und Länge). Von den 62 Koordinaten der Echtdaten ergeben sich deshalb 61 verschiedene Kartenmarker auf 59 Seiten (geprüft 2026-10-20).
13. **Fremder Bericht im Paket-Repo** (geprüft 2026-10-21, zweimal aufgetreten: Commits `4684ce4` und `f43d9bf`): Der eingecheckte `dist/pipeline_report.txt` zeigte Läufe mit den 173 Entitäten von `fuzzy-sl`, obwohl `data/raw/` des Paket-Repos leer ist. Ursache: In derselben `cmd`-Sitzung stand `WBS_ROOT` noch auf dem Demo-Repo (aus der Zeile `set WBS_ROOT=…&& python main.py harvest …`); `main.py` lud dann die Daten des Demo-Repos, schrieb den Bericht aber nach `dist/` des Paket-Repos. Behoben mit der neuen Regel in A3 und `tests/test_main.py`.
14. **Der Linkcheck liest jede HTML-Datei in `docs/`** (geprüft 2026-10-21 am Code von `step_build.linkcheck` und mit `tests/test_ci.py`), nicht nur die erzeugten Seiten. Eine von Hand angelegte Seite wie `docs/impressum.html` mit einem Link auf eine fehlende Datei ist also ein toter Link (`WARN`, mit `--strict` Exit 1); die Seite selbst bleibt beim Bauen unberührt, denn nur Dateien nach dem Muster `Q…`/`P….html` gelten als erzeugt. Ein relatives `imprint` in `site.yaml` taugt dafür nicht: Es wird nur als Text gezeigt, nie als Link (`is_linkable`).
15. **Der Determinismus-Check zeigt zugleich, ob das Eingecheckte aktuell ist** (geprüft 2026-10-21): Nach einem Lauf ist `git status --porcelain` nur dann leer, wenn `docs/` und `dist/` im Commit genau das sind, was ein frischer Lauf erzeugt, fehlende Seiten eingeschlossen (sie erscheinen als `??`). Ein zweiter Lauf fängt zusätzlich Ausgaben, die nur zufällig einmal gestimmt haben; die Probe mit wechselndem `PYTHONHASHSEED` macht das sichtbar.
16. **Windows-Runner: Temp-Verzeichnis unter 8.3-Kurzname** (geprüft 2026-10-21, erster CI-Lauf, Commit `60f96d3`): Auf `windows-latest` liegt `%TEMP%` unter `C:\Users\RUNNER~1\…`. Der Test `test_a_logo_inside_the_repository_is_copied_and_one_outside_is_refused` setzte `utils.ROOT` auf den unaufgelösten Temp-Pfad, `place_logo` vergleicht aber `source.resolve()` (Langname) mit `ROOT`; das Logo galt als „nicht im Repository“, die Datei fehlte, 1 Fehler in 101 Tests. Lokal unter Windows war der Test grün, weil dort kein Kurzname im Pfad steht. Kein Fehler im Betrieb, denn `utils.ROOT` ist beim Import aufgelöst (`.resolve()`); der Fixture wich davon ab. Behoben im Fixture (`Path(self.tmp.name).resolve()`), der Produktionscode blieb unverändert. Nachgestellt unter Linux mit einem Symlink als `TMPDIR`: vorher derselbe `FileNotFoundError`, nachher alle 101 Tests grün.
17. **Der Wrapper des Demo-Repos kannte `--strict` nicht** (geprüft 2026-10-21 am Klon von `fuzzy-sl-static`, Commit `f7d7adc`): `python main.py --strict` endete dort mit „unknown step '--strict'“ und Exit 2, und der Schritt `load` fehlte, sodass Datenwarnungen nie sichtbar wurden; der Standardwert von `command` in `site.yml` wäre sofort rot geworden. Behoben im Wrapper des Demo-Repos (`--strict` zählt `WARN`-Zeilen wie `main.py` hier, `load` steht im Standardlauf), nicht im Paket; mit S9 zieht der Orchestrator ins Paket (A4), dann entfällt der Wrapper. Zugleich geprüft: Das eingecheckte `docs/` des Demo-Repos entspricht einem frischen Bau mit dem Paket (Commit `e759577`): leerer `git status`, 173 Entitäten, 4907 Links, 0 tot, `load` ohne Warnungen; ein handgeschriebenes `docs/impressum.html` mit totem Link ergibt dort Exit 1, ohne `--strict` Exit 0. Beide Repos sind öffentlich (`fuzzy-sl-static` über den Klon, `wikibase-static` über die ohne Anmeldung geladene Seite), das Demo kann das Paket also ohne Zugangsdaten aus GitHub installieren.
18. **CSS-Regeln der Reiter erfassten die Trefferliste** (geprüft 2026-10-21 im Browser, S5): `.tabs ul` und `.tabs li a|span` aus S3b trafen auch die Liste im Suchfeld, denn das Formular sitzt in der Reiterzeile. Die Treffer standen nebeneinander (Flex-Zeile) und die Spans als Blöcke. Behoben, indem die Regeln auf `.tabs-left` und `.tabs-view` eingegrenzt wurden; `tests/test_search.py` prüft, dass die Reiterregeln die Trefferliste nicht erreichen. Wer künftig etwas in die Reiterzeile setzt, muss mit dem gleichen Fehler rechnen.
19. **Leaflet liegt über einer Liste, die auf die Karte reicht** (geprüft 2026-10-21 mit Chromium bei 700 Pixel Breite): Die Zoom-Schaltflächen der Karte haben `z-index: 1000` und wurden über der Trefferliste gemalt. Die Liste hat deshalb `z-index: 2000`; ein Test hält den Wert über 1000.
20. **Unsichtbare Zeichen im Quelltext** (geprüft 2026-10-21 durch die Mutationsprobe, S5): Ein regulärer Ausdruck mit den kombinierenden Akzentzeichen (U+0300 bis U+036F) als Literal und ein Test mit U+2028/U+2029 enthielten die Zeichen selbst; sie sind im Editor unsichtbar und ließen eine Mutation überleben. `search.js` baut den Ausdruck jetzt aus Codepunkten (`String.fromCharCode`), der Test maskiert die Zeichen; ein Scan der geänderten Quelltexte auf Steuer-, Format- und Kombinationszeichen findet keines (sichtbare Umlaute stehen weiter im Text). `render_index` maskiert U+2028/U+2029 im Index, denn in JSON sind sie erlaubt, in einem JavaScript-String vor ES2019 nicht.
21. **pip ersetzt ein Paket gleicher Version nicht** (geprüft 2026-10-21 mit einem lokalen Git-Repo als Quelle, `pip install -r` mit `wikibase-static @ git+file://…@main`): Nach einem zweiten Commit auf `main` baut pip zwar neu (`Resolved … to commit`, `Successfully built`), lässt aber die installierte Kopie bei Version 0.1.0 stehen, auch mit `--upgrade`; `search.js` fehlte danach. Erst `--force-reinstall --no-deps` tauschte sie aus. Deshalb steigt die Version mit S5 auf 0.2.0 (A4); eine frische Umgebung, wie auf den CI-Läufern, ist davon nicht betroffen. Nicht geprüft: das Verhalten gegen github.com selbst.
22. **Das RDF-Modell stammt aus dem Quelltext von Wikibase** (gelesen 2026-10-21 von `raw.githubusercontent.com/wikimedia/Wikibase`: `RdfVocabulary`, `FullStatementRdfBuilder`, `TruthyStatementRdfBuilder`, `SnakRdfBuilder`, `PropertySpecificComponentsRdfBuilder`, `TermsRdfBuilder`, die Wertbuilder, `DateTimeValueCleaner`, `JulianDateTimeValueCleaner`, `ComplexValueRdfHelper`, `RdfBuilder`): Die Seite „RDF Dump Format“ auf mediawiki.org war aus der Sandbox nicht abrufbar, die GitHub-API für das Verzeichnis ebenfalls nicht (403, Repo für die Sitzung nicht freigegeben); die rohen Dateien gingen. Folgerungen, die `rdf.py` umsetzt: `wdt:` gibt es nur für die besten Ränge (gibt es `preferred`, nur diese; sonst alle `normal`; `deprecated` nie); der Typname einer Property entsteht aus der Datentyp-ID mit `ucwords` und ohne Sonderzeichen (`globe-coordinate` → `GlobeCoordinate`, `commonsMedia` → `CommonsMedia`); der Wertknoten trägt den Typ `wikibase:<Typ>Value` und wird je Wert nur einmal geschrieben; Mengen werden mit Vorzeichen als `xsd:decimal` geschrieben; Koordinaten als `geo:wktLiteral` mit Länge zuerst. Nicht reproduzierbar sind die Hashes der Wert- und Referenzknoten (sie hängen an der PHP-Serialisierung); wir bilden eigene aus kanonischem JSON (A4, „RDF, Abweichungen“). Ein Vergleich des Exports mit den Antworten des Query Service der echten `fuzzy-sl` wurde nicht gemacht.
23. **`ontology.owl` ist älter als der Dumper** (geprüft 2026-10-21 mit einem Test): Die Datei nennt den Property-Typ `wikibase:Globecoordinate`, der Dumper schreibt `wikibase:GlobeCoordinate`, und es fehlen `wikibase:propertyType`, `wikibase:statements` und `wikibase:identifiers`, die der Dump benutzt. Wir liefern die Datei unverändert (CC0 steht in ihr) und halten die vier fehlenden Begriffe in einem Test fest; ob wir sie ergänzen, ist offen (Teil D).
24. **rdflib hängt bei bestimmten Joins** (gemessen 2026-10-21 am Export von `fuzzy-sl`, 12 456 Tripel): `?item ?claim ?statement ; rdfs:label ?l . FILTER(LANG(?l) = …)` zusammen mit einem `?reference ?p ?source`-Teil lief über 100 Sekunden, weil rdflib die Muster nach eigener Schätzung umordnet (die Reihenfolge im Text zählt nicht) und ein Kreuzprodukt entsteht. Mit dem Label des Items in einem `OPTIONAL` sind es 2,6 Sekunden. Alle Standardabfragen laufen so in unter 3 Sekunden (CPython), unter Pyodide in Node längstens 5,7 Sekunden (`references`). Wer eigene Abfragen schreibt, sollte das wissen; die Prüfung im Bau zeigt es, weil sie hängt.
25. **Ein Komma in einem YAML-Flow-Mapping teilt den Wert** (aufgefallen 2026-10-21 am Test der Standardabfragen): `title: {en: …, de: Items, die …}` las als drei Schlüssel; der deutsche Titel brach ab. Die Titel stehen jetzt in Anführungszeichen, und ein Test verlangt für jede Standardabfrage genau die Schlüssel `en` und `de`.
26. **Pyodide lässt sich in der Sandbox nicht von der CDN laden** (jsDelivr nicht erreichbar, wie schon bei der Suche): Geprüft wurde deshalb dreifach. (a) Der Python-Text der Seite (`RUNNER_PY`) und alle 12 Abfragen liefen unter echtem Pyodide 0.26.4 (npm-Paket in Node, `rdflib` 7.1.1, `isodate` und `pyparsing` als Räder aus PyPI entpackt) mit denselben Zeilenzahlen wie unter CPython: 137, 36, 18, 22, 200, 20, 60, 13, 44, 24, 3, 100; das Parsen der 12 456 Tripel dauert eine Sekunde. (b) Die Seite wurde in Chromium mit einer Pyodide-Attrappe geprüft (vorberechnete Ergebnisse, `loadPyodide` ersetzt): Status, Ausführen, Tabelle, Link auf `Q42.html`, Fehlerfall, Zurücksetzen, deutsche Oberfläche, Handybreite ohne waagerechtes Scrollen, keine Skriptfehler, vor dem Klick keine Anfrage an die CDN. (c) **Nicht gesehen:** das Laden von `pyodide.js` und die Installation von rdflib per `micropip` im Browser, also der Weg über CDN und PyPI; das geht erst auf der Live-Seite (Teil D).
27. **Der erste Bau kennt `sparql.html` noch nicht** (aufgefallen 2026-10-21 beim Entwurf): Jede Seite verlinkt auf `sparql.html`, die Seite schreibt aber erst der spätere Schritt; der Linkcheck von `build` meldete im ersten Lauf einen toten Link. `linkcheck(docs, pending=("sparql.html",))` lässt genau diesen Link durch; der Schritt `sparql` prüft danach die Links seiner eigenen Seite, ein Test hält beides fest. Wer nur `build` ausführt und nie `sparql`, hat damit einen toten Link, den kein Schritt meldet (der Standardlauf führt beide aus).
28. **Der Runner wies `ASK` und `CONSTRUCT` ab** (S6b, 2026-10-21): `wbs_run` kannte nur `SELECT`. Er liefert jetzt `kind` (`select`, `ask`, `graph`); ein `CONSTRUCT` kommt als Turtle zurück, ein `ASK` als Wahrheitswert, `run_all` zählt beides als eine Zeile beziehungsweise als Tripelzahl. Der Editor zeigt Tabelle, Antwort und Turtle; CSV und JSON gibt es nur für `SELECT` und `ASK`.
29. **rdflib zählt die vorangestellten Präfixzeilen mit** (S6b): Ein Tippfehler in Zeile 1 der Abfrage meldete `(line:29, col:8)` und eine Zeichenposition um 1 500. `errorText()` in `sparql.js` zieht Zeilen und Zeichen der Präfixe wieder ab; die Meldung selbst bleibt die des Parsers. Ein selbst geschriebenes `PREFIX wd: …` vor der Abfrage ist unschädlich (rdflib lässt die Wiederholung zu, unter echtem Pyodide geprüft).
30. **In `fuzzy-sl` gibt es keine Commons-Datei, aber eine Bild-URL** (S6b): Die Bildansicht hätte in der Demo nichts zu zeigen gehabt, wenn sie nur auf `commonsMedia` achtete. Sie erkennt deshalb jede http(s)-IRI, die auf `.jpg`, `.png`, `.gif`, `.svg`, `.webp` oder `.tif` endet, und die Standardabfrage `images` verlangt das Merkmal `image` (`site_features()`: eine `commonsMedia`-Aussage oder eine `url`-Aussage mit solchem Ende). In der Demo gibt sie eine Zeile (`Shepherd - Bruttium (Calabria) - 1911.png`). Commons-Dateien bekommen eine Vorschau mit `?width=360` und gehen über https, damit eine Pages-Seite keine gemischten Inhalte lädt.
31. **Zwei Überläufe auf dem Handy** (S6b, gefunden mit Chromium bei 390 Pixel): Die Auswahl der Beispiele ließ die Seite 48 Pixel breiter werden, und fünf Navigationslinke liefen in der Kopfzeile über; die Navigation bricht jetzt um, die Auswahl nimmt die ganze Breite. Außerdem überschrieb `display: flex` das Attribut `hidden` der Ansichtsleiste; `[hidden]` gilt jetzt dort ausdrücklich.

32. **Das Starter Pack ist die Modelltabelle** (gelesen 2026-10-21 aus `chublets-wikibase-starter-pack.zip`, gebaut 2026-10-21): `data/wikibase-property-set.csv` hat 153 Zeilen (37 `crosswalked`, 46 `codemeta-only`, 52 `wikidata-only`, 18 `chublets-addition`) mit den Spalten `status, phase, wb_label, datatype, wikidata_pid, codemeta_terms, …, confidence`; `data/wikibase-bootstrap-order.csv` nennt 11 Schritte (Instanz, Metadaten-Properties, alle Properties, Klassen, Vokabular, Personen, Beispiele, open-archaeo, Phasen 2 und 3, Export-Prüfung). Nach dem README des Packs wurde **nichts gegen Live-Wikidata geprüft** (Sandbox ohne Zugang); `docs/05-open-points.md` listet acht offene Punkte (Identity-Block in drei Varianten, 12 Registry-IDs fehlen, Q-IDs von Alligator und AMT unbekannt, Little Minion unklar, Lizenz offen, alle SPARQL- und QuickStatements-Dateien ungetestet). Was aus dem Pack kommt, trägt deshalb die Zuverlässigkeit „unverifiziert“, bis `tools/verify_wikidata.py` bei Florian gelaufen ist.
33. **open-archaeo und der Software-Usecase** (gelesen 2026-10-21 am Klon von `n4o-rse/open-archaeo` und `n4o-rse/wikibase-federation`): `open-archaeo.csv` hat 562 Einträge, `py/transform.py` macht daraus `open-archaeo-software.csv` mit 22 Spalten und 416 Software-Einträgen (sechsstellige hexadezimale IDs wie `5700bb`); das Pack bringt `data/open-archaeo-columns.csv`, die Zuordnung Spalte → Wikidata-Property mit Qualifiern. `wikibase-federation/usecases/software` (`properties.json` mit 14 lokalen Properties, `software-crosswalk.md` als „FROZEN“) nutzt dasselbe Muster wie der hier geplante Kern: lokales P1 „instance of“ und eine String-Property „equivalent Wikidata property“ (dort P15), weil `P1628` den Datentyp `url` hat und `url` auf jener Instanz gesperrt war. Das Muster ist also erprobt; ob Wikibase Cloud `url` zulässt, ist hier nicht entscheidend, denn die statische Seite kennt kein Sperren.
34. **Fremde IDs im Wert kollidieren mit lokalen** (Folgerung aus dem Loader, 2026-10-21): Ein Item-Wert `Q28865` (Python bei Wikidata) wird auf der statischen Seite zur lokalen `Q28865`, sobald es sie gibt; A4 „Entitätswert außerhalb der Daten“ verlinkt nur, wenn die ID in den Daten fehlt. Der Wikidata-Import legt deshalb für jede benutzte Entität eine lokale ID an (Stub mit Zwilling in P4) und schreibt nie eine fremde ID in einen Wert. Für die echte Wikibase mit Federation gilt das Gegenteil: dort ist ein `wd:Q…`-Wert der Normalfall; der Push übersetzt jeden Stub deshalb in den föderierten Wert (A4 „Wikidata-Werte beim Push“).
35. **Wikidata ist aus der Sandbox nicht erreichbar** (geprüft 2026-10-21: `curl` auf `https://www.wikidata.org/w/api.php` endet mit HTTP-Code 000; GitHub-Klone gehen). Der Wikidata-Importer (S7d) wird deshalb mit Fixtures getestet, der echte Lauf geschieht bei Florian.
36. **`step_from_csv.py` ist ein Platzhalter** (gelesen 2026-10-21): `main()` ruft nur `utils.nothing_to_do`. Der Loader liest `data/derived/entities/*.json` bereits (A4 „Ladeorte“); S7 muss also kein Format erfinden, sondern CSV in das Format übersetzen, das `harvest` ablegt.
37. **QuickStatements-Syntax im Pack** (gelesen 2026-10-21 in `examples/alligator.qs`): tabulatorgetrennt, `CREATE`/`LAST`, Zeit als `+2021-06-04T00:00:00Z/11`, Qualifier als weitere Paare hinter dem Wert. Das Pack nennt alle `.qs`-Dateien ungetestet. Koordinaten (`@lat/lon`), Monolingual (`de:"Text"`), Entfernen mit `-` und Belege mit `S`-Präfix sind hier **aus dem Gedächtnis**, nicht aus einer Quelle geprüft; vor S7e gegen die QuickStatements-Hilfe lesen. Der Dialekt von `wbqs/parser.py` (gelesen 2026-10-21) ist enger: drei Spalten; Items als `Q…`, `wd:Q…` oder Entity-URI, dazu String, URL, External-ID und Koordinaten; keine Qualifier, Belege, Labels, Zeit; `wd:` für föderierte Properties und Werte. Der Update-Kanal übernimmt dessen `wd:`-Schreibweise.
38. **`wikibase-federation` schreibt, aber nicht alles** (gelesen 2026-10-21 am Klon): `wbqs` meldet sich per Action API an und schreibt mit Wiederholung bei Fehlern; Anlegen und Wiederverwenden von Properties (bei Label-Konflikt wird die vorhandene benutzt) ist im Usecase `software` mit `properties.json` und `items.json` idempotent gelöst, die Anmeldedaten stehen in einer nicht eingecheckten `config.ini`. Föderierte Werte laufen über `wbcreateclaim` mit voller Entity-URI als `id` (README „Why the API and not QuickStatements?“; nach dem README noch alpha). Qualifier, Belege, Labels und Zeit gibt es nicht (Befund 37).
39. **Das JSON in `data/derived/` ist die Eingabe, die `wbeditentity` kennt** (Folgerung, 2026-10-21; **nicht gegen eine Wikibase ausprobiert**): Das Format ist das von `wbgetentities` und `Special:EntityData`; `wbeditentity` nimmt Entitätsdaten im selben Aufbau (Labels, Descriptions, Aliases, Claims mit Qualifiern und References) entgegen. Auszutauschen sind IDs der Entitäten und Werte (Zuordnung CSV-ID → Ziel-ID), Hashes und `lastrevid`. Ob die Ziel-Wikibase `url` zulässt und Federation eingeschaltet hat, ist ungeprüft (`https://chublets-wikibase.de/wiki/Main_Page` war aus der Sandbox nicht abrufbar, Fehler des Abrufdienstes).
40. **Testlauf des Pakets in der Sandbox** (2026-10-21, frischer Klon von `main`, mit `rdflib` 7, PyYAML und Jinja2 installiert): 244 Tests, OK; `python main.py --strict` zweimal Exit 0. Ohne `rdflib` schlagen 31 der 200 laufenden Tests fehl (23 Fehler `No module named 'rdflib'`, 8 Abweichungen), unverändert mit und ohne diesen Patch; das ist ein Umgebungsfehler der Sandbox, keiner des Pakets.

### A2 Zielbild

```
 Wikibase (API)                       CSV + Mapping
      │ harvest (S4, einziger Netzschritt)   │ from-csv (S7)
      ▼                                      ▼
 data/raw/  Wikibase-JSON + manifest.json    data/derived/  dasselbe Format
      └───────────────────┬──────────────────┘
                          │ build (S2, S3)
        ┌─────────────────┼───────────────────────┐
        ▼                 ▼                       ▼
   docs/ Seiten      dist/*.ttl  (S6)        docs/sparql.html (S6)
   Suche, Karte      Wikibase-RDF-Modell     rdflib unter Pyodide
        │
        ▼
   GitHub Pages
```

Das Ergebnis hat diese prüfbaren Eigenschaften:

1. **Vollständig:** Jede Q-/P-ID aus `data/raw/` bzw. `data/derived/` hat eine Seite. Der Bericht nennt Entitäten und Seiten, die Differenz ist 0.
2. **Read-only und statisch:** Die veröffentlichten Seiten senden keine Anfragen an die Quell-Wikibase. Erlaubt sind nur Commons-Bilder, Kartenkacheln und Links, die der Nutzer anklickt. Eine Ausnahme gibt es erst auf Klick: `sparql.html` lädt nach „Ausführen“ Pyodide von `cdn.jsdelivr.net` und rdflib von PyPI (A4, „SPARQL, Laufzeit“); eine Seite, die nur gelesen wird, lädt dort nichts.
3. **Navigierbar:** Jeder interne Q-/P-Link löst auf eine vorhandene Seite auf. Der Linkcheck im Bericht meldet 0 tote interne Links.
4. **Deterministisch:** Zwei Läufe hintereinander, `git status` sauber.
5. **Inkrementell:** `harvest` ohne Änderungen an der Quelle schreibt nichts. Der Bericht nennt die Zahl der Requests (nur Listen- und Info-Abfragen).

### A3 Querschnittsregeln

- Rohdaten liegen unter `data/raw/`, unverändert wie erhalten, nicht von Hand ändern. Was ein Skript daraus macht, geht nach `data/derived/`, `dist/` oder `docs/`.
- Wiederverwendung heißt kopieren, nicht referenzieren. Ausnahme: ein gemeinsames Vokabular, das per w3id-IRI importiert wird.
- Kopierter Code bringt seine Prüfungen mit. Eine Absicherung, die beim Kopieren verloren geht, ist die gefährlichste Form der Wiederverwendung.
- **Keine Uhr im Output.** Kein Generator ruft `datetime.now()` auf. Datumsangaben kommen aus `RELEASE_DATE` (in `py/wikibase_static/utils.py`) oder aus den Quelldaten selbst.
- **Zeilenenden LF.** Jedes Repo der Familie hat eine `.gitattributes` mit `* text=auto eol=lf`; sonst weichen unter Windows die Hashes der Rohdaten ab (siehe S4, „Erledigt“).
- **Zweimal laufen lassen, `git status` bleibt sauber.** `dist/pipeline_report.txt` enthält deshalb nur, was die Schritte sagen, keine Laufzeiten (die erscheinen nur im Terminal).
- **Der Bericht gehört zum Repo seiner Daten.** `python main.py` schreibt `dist/pipeline_report.txt` nur bei einem vollständigen Lauf und nur, wenn `WBS_ROOT` nicht gesetzt ist oder auf das Repo selbst zeigt. Zeigt es auf ein Demo-Repo, laufen die Schritte dort, der Bericht des Paket-Repos bleibt unberührt, und das Terminal sagt „report not written“ (Befund 13). Vor einem Lauf im Paket-Repo steht in `cmd` `set WBS_ROOT=`, damit die Variable der Sitzung nicht nachwirkt.
- **CI prüft, was lokal gilt.** Der Workflow ruft `python main.py --strict` zweimal auf und verlangt nach jedem Lauf ein leeres `git status --porcelain` (Befund 15); er enthält keine eigene Prüflogik, die lokal nicht läuft. Neue Prüfungen kommen in die Schritte (als `WARN`) und in `tests/`, nicht in die YAML-Datei.
- **Netzwerk nur in den Verben `harvest` und `import-wikidata`** (zweites Verb: Vorschlag 2026-10-21, S7d). Alles andere läuft offline gegen die Daten auf der Platte. Beide sind nie Teil des Standardlaufs, sondern haben ein eigenes Verb: `python main.py harvest`, `python main.py import-wikidata`.
- **Höflicher Harvest.** Ehrlicher User-Agent mit Kontaktadresse, Pause zwischen Requests, `Retry-After` und `maxlag` beachten. Verlangt ein Host eine Bot-Challenge (z. B. Anubis), bricht `harvest` mit einer klaren Meldung ab. Es wird nicht versucht, sie zu lösen oder zu umgehen; der Weg ist dann `--from-dir` mit im Browser gesicherten JSON-Dateien.
- **Die Seiten zeigen, was die Quelle sagt.** Werte werden formatiert, nicht repariert (ein Tippfehler in einer URL bleibt sichtbar, Befund 7). Zu einem Link werden nur `http://`, `https://`, `ftp://` und `ftps://`; alles andere (etwa `javascript:`) steht als Text.
- Befehle für Windows `cmd`, jeder in **einer** Zeile, ohne Fortsetzungszeichen.
- Mermaid-Diagramme nutzen das feste Farbschema der Familie (Subject/Object grau, RealObject dunkelgrün, Class dunkelorange, Term dunkelviolett, OWL weiß, PropMeta amber).

### A4 Beschlusslage

| Frage | Beschluss | seit |
|---|---|---|
| Aufteilung in Repos | Variante A: ein Paket-Repo `wikibase-static` (Subcommands `harvest`, `from-csv`, `build`, `rdf`, …) plus Template-Repo `wikibase-static-template` | 2026-10-20 |
| Organisation und Name | `https://github.com/n4o-rse/wikibase-static` | 2026-10-20 |
| Reihenfolge Repo und Skill | erst das Repo, danach der Skill daraus | 2026-10-20 |
| Größenordnung | dreistellig (einige hundert Entitäten); keine Server-Suche, keine Pagination nötig | 2026-10-20 |
| Entitätstypen | Items und Properties; Lexeme und Media-Entitäten außerhalb des Umfangs | Vorschlag |
| Datentypen | Item, Property, String, External-ID (mit Formatter-URL), URL, Zeit, Quantity, Monolingual Text, Koordinaten, Commons-Datei | 2026-10-20 |
| Bilder | Commons-Dateiname (z. B. P18) über `Special:FilePath`; zusätzlich Bild-URL direkt anzeigen | 2026-10-20 |
| Karte | Leaflet für jeden Koordinatenwert | 2026-10-20 |
| Sprachen | Standardsprache (de oder en) in `site.yaml`, Umschalter für zweisprachige Anzeige, Fallback auf die Standardsprache | 2026-10-20 |
| Suche | Autocomplete wie Wikidata, im Browser. Ein Treffer zeigt Label, ID und Beschreibung. Gesucht wird in Labels (jeder Sprache), Aliasen und IDs, **nicht** in Beschreibungen | 2026-10-20 (Umfang der Suchfelder präzisiert 2026-10-21, S5) |
| Suche, Technik | Eigener Abgleich in `static/search.js` statt MiniSearch (ersetzt den Vorschlag von 2026-10-20). Gründe: Bei dreistelliger Größe (173 Entitäten, 368 durchsuchbare Zeichenketten) genügt ein linearer Durchlauf; die Regeln (ID, Akzente, Rangfolge) sind klein und lassen sich unter Node vollständig testen; es kommt keine Fremdbibliothek hinzu, die kopiert, mit Lizenz abgelegt und geprüft werden müsste (A3). MiniSearch wurde nicht ausprobiert, über seine Leistung wird hier nichts behauptet | 2026-10-21 (S5) |
| Suche, Index | `docs/assets/search-index.js`: ein Skript, das `window.WBS_SEARCH_INDEX` setzt, kein reines JSON, damit es auch von `file://` lädt (`fetch()` täte das nicht). Kanonisches JSON (Schlüssel sortiert, kompakt, UTF-8, U+2028/U+2029 maskiert), Einträge in ID-Reihenfolge (Items zuerst, numerisch). Felder je Eintrag: `id`, `l` (angezeigtes Label je Sprache der Seite, mit Fallback wie `model.pick_text`), `d` (Beschreibung ebenso), `x` (Labels in weiteren Sprachen), `a` (Aliase aller Sprachen); dazu `languages` und `version`. Der Index hängt nur von den Daten und den beiden Sprachen aus `site.yaml` ab. Er wird beim ersten Fokus auf das Feld nachgeladen, eine nur gelesene Seite holt ihn nie | 2026-10-21 (S5) |
| Suche, Treffer | Vergleich ohne Akzente und Groß-/Kleinschreibung (NFD ohne U+0300 bis U+036F). Rangfolge, kleiner ist besser: 0 ID genau, 1 Label ganz, 2 Alias ganz, 3 Label beginnt damit, 4 Alias beginnt damit, 5 ID beginnt damit (ab zwei Zeichen), 6 alle Suchwörter beginnen Wörter des Labels, 7 des Alias, 8 Teilstring im Label, 9 im Alias (Teilstring ab drei Zeichen). Gleicher Rang: nach Label (`Intl.Collator`, numerisch, in der Seitensprache), Treffer nur über ID-Anfang in ID-Reihenfolge. Höchstens 10 Treffer; trifft nur ein Alias oder ein Label einer anderen Sprache, steht diese Zeichenkette kursiv neben dem Label | 2026-10-21 (S5) |
| Suche, Bedienung | ARIA-Combobox mit Listbox; Pfeil auf/ab wählt, Enter öffnet den gewählten oder sonst den ersten Treffer, Escape schließt, danach leert es das Feld. Treffer sind Links auf `<ID>.html`. Ein Mausdruck in der Liste nimmt dem Feld den Fokus nicht. Anzeige und Hilfstexte folgen dem Sprachumschalter (Beobachter auf `data-lang`); die Texte kommen für `en` und `de` aus `render.STRINGS` über das Attribut `data-text`. Das Formular trägt `hidden`, das Skript hebt es auf: ohne JavaScript ist kein Feld zu sehen, das nicht funktionieren kann. Texte werden mit `textContent` gesetzt, nie als HTML | 2026-10-21 (S5) |
| Suche, Layout | Das Feld sitzt in der Reiterzeile zwischen den Reitern rechts und dem Sprachumschalter; die Liste hängt darunter, rechtsbündig, 26 rem breit, `z-index: 2000` (Befund 19). Die Reiterregeln sind auf `.tabs-left` und `.tabs-view` begrenzt (Befund 18). Unter 48 rem bekommt das Feld über `display: contents` eine eigene Zeile, die Liste füllt die Breite | 2026-10-21 (S5) |
| Suche, Schrittfolge | `search` läuft nach `build`; er warnt (`WARN`), wenn indizierte Entitäten keine Seite in `docs/` haben, und ist ohne Entitäten „nothing to do“. Die Datei `search.js` kopiert `build` wie die anderen Assets, der Index kommt nur von `search` | 2026-10-21 (S5) |
| Version | 0.2.0 ab S5 (`__init__.py`, `CITATION.cff`), weil pip ein Paket gleicher Version nicht ersetzt (Befund 21). Die Version steht im Seitenfuß; jede Änderung der Version ändert damit alle Seiten der Demo-Repos, deren `docs/` neu gebaut und mit committet werden muss | 2026-10-21 (S5) |
| Version, S6 | 0.3.0 ab S6 (`__init__.py`, `CITATION.cff`), aus demselben Grund wie bei 0.2.0 (Befund 21); alle Seiten der Demo-Repos ändern sich (Seitenfuß, Navigationslink), deren `docs/` ist neu zu bauen und mit zu committen | Vorschlag 2026-10-21 (S6) |
| Abhängigkeit `rdflib` | `rdflib>=7` in `pyproject.toml` und `requirements.txt`, damit das Demo-CI sie über das Paket bekommt; importiert wird sie erst im Schritt, nach der Prüfung auf Daten | Vorschlag 2026-10-21 (S6) |
| `site.yaml`, `rdf_base` | neuer optionaler Schlüssel: Basis-URI des RDF-Exports, Standard ist `source.url`; eine ungültige Angabe ist `WARN` mit Rückfall. Im Demo-Repo ist jetzt auch `pages_url` gesetzt (`https://n4o-rse.github.io/fuzzy-sl-static/`), weil die DCAT-Distributions absolute Download-URLs brauchen; damit tragen alle Seiten einen kanonischen Link (Teil D, früher „optional“) | Vorschlag 2026-10-21 (S6) |
| RDF, Modell | Wikibase-RDF-Modell wie der Dump von Wikibase (Quelltext gelesen, Befund 22): Entität `wikibase:Item`/`wikibase:Property`; Terme `rdfs:label`, `skos:prefLabel`, `schema:name`, `schema:description`, `skos:altLabel`; Statements `p:` → `wds:`-Knoten (`wikibase:Statement`, `wikibase:rank`, `wikibase:BestRank`) mit `ps:`, `pq:`, `pr:`; `wdt:` nur für die besten Ränge; Wertknoten `wdv:` für Zeit, Menge und Koordinate (`psv:`, `pqv:`, `prv:`); `wdno:` für „kein Wert“, ein Blankknoten für „unbekannter Wert“; Fundstellen als `prov:wasDerivedFrom` auf `wdref:`; Dokumentknoten `data:Q1` (`schema:Dataset`, `schema:about`, `schema:version`, `schema:dateModified`, `cc:license`); Properties mit `wikibase:propertyType`, `claim`, `directClaim`, … und OWL-Klassifikation | Vorschlag 2026-10-21 (S6) |
| RDF, Abweichungen vom echten Dump | (a) Hashes der Wert- und Referenzknoten sind eigene (MD5 bzw. SHA-1 über kanonisches JSON); (b) keine normalisierten Werte (`wdtn:`), keine Sitelinks, keine `wikibase:Dump`-Metadaten; (c) Blankknoten haben stabile Namen (MD5 über Kontext); (d) nicht unterstützte Datentypen werden nicht exportiert (`WARN` mit Zahl); (e) Zeit wie der `DateTimeValueCleaner`: Gregorianisch und Genauigkeit unter Tag bereinigt (Monat und Tag 0 → 1, Tag über Monatsende gekürzt, v. Chr. nach XSD 1.1), Julianisch ab Tagesgenauigkeit umgerechnet, andere Kalender und Jahr 0 bleiben Text | Vorschlag 2026-10-21 (S6) |
| RDF, Basis-URI | `rdf_base`, sonst `source.url`; fehlen beide, gilt `https://wikibase.example` mit Hinweiszeile (kein `WARN`, sonst wären die Fixture-Läufe von `--strict` rot). Der Dateiname ist Host (und Pfad) der Basis: `dist/fuzzy-sl.wikibase.cloud.ttl` | Vorschlag 2026-10-21 (S6) |
| RDF, Turtle | Eigener Writer in `rdf.py` statt des Serialisierers von rdflib (dessen Layout ist nicht zugesichert): Präfixe sortiert, Subjekte in fester Gruppenfolge und natürlicher Ordnung (`Q2` vor `Q10`), `a` zuerst, Objekte sortiert; Zwischenform sind sortierte N-Triples. Der Schritt liest das Turtle mit rdflib zurück und vergleicht es isomorph mit den Tripeln (Abweichung ist `WARN`). Kopfzeilen: Quelle, Paketversion, Datenstand (`latest_modified`), Lizenz; keine Uhrzeit | Vorschlag 2026-10-21 (S6) |
| RDF, DCAT 3 | Catalog ist die Wikibase (`<base>/catalog`: `dcterms:title`, `dcat:landingPage` auf die Quelle, `dcterms:conformsTo` auf die Wikibase-Ontologie) mit den Unterkatalogen `…/catalog/items` und `…/catalog/properties` (`dcterms:hasPart`); Dataset ist jede Entität: der Knoten `data:Q1` ist zusätzlich `dcat:Dataset` (kein neuer Knoten) mit `dcterms:identifier`, `title` und `description` in allen Sprachen, `modified`, `license`, `isPartOf`, `subject` (die Entität) und `dcat:landingPage` (HTML-Seite); Distributions je vorhandener Datei: JSON (`json/Q1.json`, mit `byteSize`), Turtle (`ttl/Q1.ttl`), HTML (`accessURL`); am Katalog hängen außerdem der Gesamtexport und die Ontologie als Datasets. Ein Catalogue je Q- oder P-ID wurde erwogen und verworfen: ein Katalog mit genau einem Dataset wäre Überbau ohne Inhalt (`dcat:Catalog` ist in DCAT 3 zwar Unterklasse von `dcat:Dataset`, nötig ist es hier nicht). Distributions gibt es nur mit `pages_url`; ohne sie steht eine Hinweiszeile, kein `WARN`. IRIs: `<base>/catalog/…` und `<base>/distribution/<ID>-json|ttl|html` (im Namensraum der Quell-Wikibase, aber nicht von ihr vergeben) | Vorschlag 2026-10-21 (S6; von Florian im Chat vorgeschlagen, Ausgestaltung offen) |
| RDF, Dateien | `dist/<host>.ttl` (versioniert), `docs/downloads/<host>.ttl` (Byte-Kopie, wird veröffentlicht), `docs/downloads/wikibase-ontology.ttl`, `docs/ttl/<ID>.ttl` (Aussagen, Fundstellen, Wertknoten, Dataset und Distributions der Entität; Katalogtripel nur in der Gesamtdatei), `docs/json/<ID>.json` (Byte-Kopie der archivierten Datei). Veraltete Dateien in `docs/ttl/` und `docs/json/` werden entfernt. Größe beim Demo: `docs/` 5,6 MB | Vorschlag 2026-10-21 (S6) |
| RDF, Ontologie | `docs/ontology.owl` aus `wikimedia/Wikibase` (die Datei nennt CC0 1.0), unverändert als Turtle im Paket (`data/wikibase-ontology.ttl`, Kopfzeilen nennen Herkunft) und veröffentlicht als `docs/downloads/wikibase-ontology.ttl`; verlinkt von der Query-Seite und als Dataset im Katalog. Das Paket ergänzt sie nicht (Befund 23) | Vorschlag 2026-10-21 (S6) |
| SPARQL, Seite | `docs/sparql.html` mit Navigationslink „SPARQL“ auf jeder Seite; Abfragen in editierbaren Feldern mit Ausführen, Zurücksetzen und `.rq`-Download (`docs/downloads/queries/<id>.rq`, mit den benutzten Präfixen); alle Präfixe der Namensräume werden jeder Abfrage vorangestellt (so auch nach Änderung im Browser); Ergebnis als Tabelle, IRIs der Wikibase verlinken auf die Seite der Entität, Zellwerte zentral maskiert, höchstens 500 Zeilen mit Angabe der Gesamtzahl; zweisprachig wie die übrigen Seiten | Vorschlag 2026-10-21 (S6) |
| SPARQL, Laufzeit | Pyodide 0.26.4 und rdflib 7.1.1, beides fest eingestellt (`sparql.py`); beides lädt erst beim ersten Klick auf „Ausführen“ (Pyodide von `cdn.jsdelivr.net`, rdflib per `micropip` von PyPI), die Turtle-Datei der Seite per `fetch` (von `file://` geht das nicht, die Seite sagt es). Der Python-Text `RUNNER_PY` steht einmal in `sparql.py` und läuft unverändert im Browser und im Bau. Kein Endpoint; was getippt wird, verlässt den Browser nicht | Vorschlag 2026-10-21 (S6; Technik aus der Zeile „SPARQL“ vom 2026-10-20) |
| SPARQL, Abfragen | `queries.yaml` im Wurzelverzeichnis des Site-Repos ersetzt den Standardsatz `data/queries.default.yaml` (13 Abfragen, zweisprachig, für jede Wikibase geeignet, darunter zwei zu den DCAT-Katalogen; `coordinates` und `images` tragen eine `#defaultView`-Zeile); `@@lang@@` steht für die Standardsprache; `requires:` (Datentyp oder `reference`, `qualifier`, `alias`, `preferred`, `somevalue`, `distribution`) lässt eine Abfrage weg, wenn die Daten nichts dafür haben (das Log nennt sie); PREFIX-Zeilen im Text sind ein Fehler. Aufbau nach dem Skill `wdt-sparql` (Abfragen als Quelle, Seite und `.rq` daraus), ohne das qmd-Notebook | Vorschlag 2026-10-21 (S6) |
| SPARQL, Prüfung | Jede verbliebene Abfrage läuft im Bau mit dem Python der Seite gegen die veröffentlichte Datei; **keine Zeile oder ein Fehler ist `WARN`** (unter `--strict` ein Fehler). SPARQL antwortet auf eine vertippte IRI mit „keine Zeilen“, deshalb gilt eine leere Beispielabfrage als Fehler im Export, bis das Gegenteil bewiesen ist | Vorschlag 2026-10-21 (S6) |
| SPARQL, Schrittfolge | `sparql` läuft nach `rdf`; fehlt `dist/<host>.ttl`, ist das `WARN` („run the rdf step first“), ebenso eine `docs/downloads/<host>.ttl`, die von `dist/` abweicht; ohne Entitäten „nothing to do“. `build` meldet den noch nicht geschriebenen Link auf `sparql.html` nicht (`linkcheck(…, pending=)`, Befund 27) | Vorschlag 2026-10-21 (S6) |
| SPARQL, Editor (S6b) | `docs/query.html` mit Navigationslink „Query“/„Abfrage“: ein freies Eingabefeld (Strg+Eingabe führt aus), eine Auswahl „Beispiele“ mit dem Standardsatz der Seite (die erste Abfrage steht zu Beginn im Feld), „Link zu dieser Abfrage kopieren“ (die Abfrage steht in der Adresse als `#q=…`, ein Aufruf füllt das Feld, führt aber nichts aus), Ergebnis als Tabelle, bei `Point(…)`-Werten auch als Karte, bei Bilddateien als Bilder, Download als CSV und als „SPARQL 1.1 Query Results JSON“; `SELECT`, `ASK`, `CONSTRUCT`. Die Beispielseite `sparql.html` bleibt und verweist je Abfrage mit „Im Abfrage-Editor öffnen“ auf den Editor. Dieselbe Laufzeit und derselbe `RUNNER_PY`; Pyodide wird einmal je Seitenaufruf gestartet | Vorschlag 2026-10-21 (S6b) |
| SPARQL, Ansichten (S6b) | Die Ansicht folgt dem Ergebnis: Karte, wenn eine Spalte `Point(Länge Breite)` (WKT, Erde) enthält, Bilder, wenn eine Spalte eine Bild-IRI enthält (Befund 30), immer Tabelle. Eine Kommentarzeile `#defaultView:Map`, `#defaultView:ImageGrid` oder `#defaultView:Table` am Anfang der Abfrage wählt die zuerst gezeigte Ansicht, wie beim Query Service von Wikidata; andere Namen (`BubbleChart`, …) gibt es nicht und werden ignoriert. Karte: Leaflet mit OSM-Kacheln wie auf den Entitätsseiten, Beschriftung ist das erste Literal der Zeile, Link auf die Seite der Entität; höchstens 500 Zeilen (`MAX_ROWS`), Bilder höchstens 200. Punkte auf anderen Himmelskörpern werden nicht gezeigt | Vorschlag 2026-10-21 (S6b) |
| Version, S6b | 0.3.1 (`__init__.py`, `CITATION.cff`), damit `pip install --upgrade` das Paket ersetzt; alle Seiten der Demo ändern sich wieder (Version im Seitenfuß, neuer Navigationslink) | Vorschlag 2026-10-21 (S6b) |
| SPARQL | RDF im Wikibase-Modell erzeugen, Abfrage im Browser über rdflib unter Pyodide (kein Endpoint) | 2026-10-20 |
| Zwischenformat | Wikibase-JSON, wie `Special:EntityData` / `wbgetentities` es liefert; `from-csv` erzeugt dasselbe | Vorschlag |
| Ablage CSV-Variante | Eingabe-CSV unter `data/csv/`, erzeugtes Wikibase-JSON unter `data/derived/`; `data/raw/` bleibt dem Harvest vorbehalten | Vorschlag |
| Harvest inkrementell | IDs und `lastrevid` in einer Abfrage je Namespace (`generator=allpages` mit `prop=info`, 500 pro Request) mit `data/raw/manifest.json` vergleichen, nur Geändertes per `wbgetentities` laden (50 pro Request). Gegenüber dem früheren Vorschlag (`wbgetentities&props=info` je Batch) spart das die Info-Requests; Seiten-`lastrevid` und Entitäts-`lastrevid` sind bei Wikibase dieselbe Revision. Bestätigt am Erst- und Zweitlauf gegen `fuzzy-sl` (Seiten- und Entitäts-`lastrevid` stimmen überein) | 2026-10-20 |
| Harvest, SPARQL als Quelle | `--source sparql` ist nicht umgesetzt; der Query Service kann nachhinken und hängt evtl. hinter derselben Challenge. Wird nur gebaut, wenn der Lauf gegen `fuzzy-sl` es nötig macht | zurückgestellt 2026-10-20 |
| Datum im Manifest | nur serverseitige Werte (`lastrevid`, `modified`; `latest_modified` ist das Maximum davon), keine lokale Uhrzeit | Vorschlag |
| Ablage Roh-Entitäten | `data/raw/entities/<ID>.json` (ein Entitätsobjekt, wie `wbgetentities` es liefert, Schlüssel sortiert) plus `data/raw/manifest.json` (`source`, je Entität `lastrevid`, `modified`, `sha256`). Die Sortierung der Schlüssel ändert nichts am Inhalt, ist aber nötig für byte-gleiche Läufe | Vorschlag |
| Quelle im Manifest | `--url` wird im Manifest gemerkt; ein Verzeichnis `data/raw/` gehört genau einer Wikibase, eine andere `--url` wird abgelehnt. Gelaufen wird im Demo-Repo (`WBS_ROOT`), nicht im Paket-Repo | Vorschlag |
| Löschungen | Entitäten, die die Quelle nicht mehr listet, werden aus `data/raw/` entfernt (nicht bei `--from-dir`, dort fehlt die vollständige Liste) | Vorschlag |
| HTTP-Client | nur Standardbibliothek (`urllib`), kein `requests`; nur GET, Retry bei 429/5xx und `maxlag`, `Retry-After` wird beachtet, 1 s Pause, `maxlag=5` | Vorschlag |
| User-Agent | `wikibase-static/<Version> (+<Kontakt>; static archive, read-only)`; Kontakt per `--contact` oder `WBS_CONTACT`, Standard ist die Repo-URL | Vorschlag |
| Exit-Codes Harvest | 0 ok, 1 Fehler (u. a. Host nicht erreichbar), 2 Bot-Challenge oder keine API unter der Adresse | Vorschlag |
| Paketform | Paket unter `py/wikibase_static/` mit `pyproject.toml`, damit das Template-Repo es per pip installieren kann; Abweichung vom flachen `py/<repo>_utils.py` der Familie: `utils.py` liegt im Paket | Vorschlag |
| Lizenz | MIT; Copyright-Zeile aktuell „Florian Thiery“, bei Bedarf auf die Organisation ändern | Vorschlag |
| Seiten-URL-Schema | flach: `docs/Q123.html`, `docs/P1.html`; alle Seiten in einem Ordner | 2026-10-20 |
| Sprachen, Standard | `en` als Standardsprache, `de` als zweite Sprache mit Umschalter; Fallback auf `en`. Pro Site in `site.yaml` änderbar (die Chublets-Demo kann `de` als Standard setzen) | 2026-10-20 |
| Föderierte Properties und Werte | nur verlinken (Wikidata-Seite im neuen Tab), keine eigene Seite | 2026-10-20 |
| Fußzeile pro Seite | Quelle (Link auf die Quell-Wikibase und die Originalseite der Entität), Stand (`modified` der Entität aus dem Manifest), Lizenz (Text und Link aus `site.yaml`; ohne Eintrag gilt CC0 1.0, siehe Zeile „Lizenz, Standard“; geändert 2026-10-20 auf Wunsch, vorher stand dort „Lizenz nicht angegeben“) | 2026-10-20 |
| `site.yaml`, Schlüssel | `title`, `description`, `logo` (optional), `colour` (optional), `source.url` (muss zum Manifest passen), `license.name`, `license.url`, `languages.default`, `languages.second`, `imprint` (Text oder URL), `pages_url` (optional), `formatter_property` (optional, Standard `P1630`, siehe Befund 10) | 2026-10-20 (bestätigt mit S3; `formatter_property` neu) |
| Demo-Repo, Gerüst | `fuzzy-sl-static` bekommt bis S9 ein dünnes Gerüst (`main.py`-Wrapper, `requirements.txt` mit pip-Installation von GitHub, `README.md`, `.gitignore`), kein `LICENSE`; die Datenlizenz gilt seit 2026-10-20 als CC0 (Zeile „Lizenz, Standard“), eine `LICENSE`-Datei wird nur auf Wunsch angelegt | 2026-10-20 |
| Orchestrator im Paket | der Orchestrator (`main.py`-Logik) zieht in S9 ins Paket (`python -m wikibase_static`); das `main.py` im Wurzelverzeichnis wird zum dünnen Aufruf | Vorschlag |
| Schritt `load` | `python main.py load` liest und prüft die Daten, schreibt nichts, steht im Standardlauf nach `from-csv`; ohne Daten meldet er „nothing to do“ (S2) | Vorschlag |
| Ladeorte | `data/raw/entities/*.json` und `data/derived/entities/*.json`, eine Entität je Datei (auch die `Special:EntityData`-Form wird gelesen). Dieselbe ID in beiden Orten: erste (`raw`) gewinnt, `WARN` | Vorschlag |
| Statement-Reihenfolge | numerische Property-ID, innerhalb einer Property die Reihenfolge der Quelle; Qualifier und Reference-Teile nach `qualifiers-order` bzw. `snaks-order`, sonst numerisch (Befund 9) | Vorschlag |
| Validierung | Probleme sind `WARN`-Zeilen, nie ein Abbruch; geprüft werden unlesbares JSON, fehlende ID, Datei- und ID-Name, Typ gegen ID, Datentyp gegen Wertetyp und Pflichtschlüssel des Werts, nicht unterstützte Datentypen, fehlende Entitäten (einmal je ID, mit den ersten fünf Verweisenden) und Abweichungen zum Manifest. `--strict` macht daraus Fehler | Vorschlag |
| Label-Auflösung | nur aus den geladenen Entitäten, nie aus dem Netz; erste Sprache der Liste mit Label, sonst die alphabetisch erste vorhandene, sonst die ID selbst | Vorschlag |
| Datei- und Seitenaufbau | Je Entität `docs/<ID>.html`, dazu `docs/index.html` (Titel, Beschreibung, Zählung, Tabellen der Items und Properties) und `docs/assets/` (`style.css`, `app.js`, `search.js`, `map.js`, `vendor/leaflet/`, optional `logo/`; `search-index.js` kommt von `search`). Die Quelltexte liegen im Paket (`templates/`, `static/`, in `pyproject.toml` als Paketdaten eingetragen) und werden beim Bauen nach `docs/assets/` kopiert | Vorschlag |
| Abhängigkeiten ab S3 | PyYAML und Jinja2; importiert werden sie erst nach der Prüfung auf vorhandene Daten, damit `--list`, `--dry-run` und ein leeres Repo sie nicht brauchen | Vorschlag |
| Fehlende `site.yaml` | ohne `site.yaml` laufen Standardwerte (Titel aus der Quell-Adresse, sonst „Wikibase archive“, Lizenz CC0 1.0) mit einer Hinweiszeile, kein `WARN`. Ungültige Werte in `site.yaml` sind `WARN` mit Rückfall auf den Standard | Vorschlag |
| Sprachumschalter, Technik | Zweisprachiger Text steht als zwei `<span class="l" lang=…>`; ein Stil im Seitenkopf blendet je nach `data-lang` am `<html>`-Element die andere Sprache aus, ohne JavaScript gilt die Standardsprache. Sind beide Texte gleich oder fehlt der zweite (Fallback auf die Standardsprache), steht nur ein einfacher Text. Die Wahl merkt sich `localStorage` (Schlüssel `wbs-lang`). Oberflächentexte gibt es für `en` und `de`, jede andere Standardsprache fällt dafür auf `en` zurück | Vorschlag |
| Leaflet | Leaflet 1.9.4 liegt als Kopie im Paket (`static/vendor/leaflet/`, mit Lizenz), kein CDN; nur die Kacheln kommen von `tile.openstreetmap.org` (A2, Eigenschaft 2). Eine Karte je Seite, sie zeigt alle verschiedenen Erdkoordinaten der Entität (Haupt-, Qualifier- und Referenzwerte); Koordinaten auf einem anderen Globus oder außerhalb des Wertebereichs stehen nur als Text | Vorschlag |
| Koordinatenanzeige | `49.9929° N, 8.2473° E`, höchstens so viele Nachkommastellen wie die Genauigkeit in Grad hergibt, nachgestellte Nullen entfallen (die Quelle speichert 39.08002, nicht 39.080020); der Text verlinkt auf OpenStreetMap in einem neuen Tab | Vorschlag |
| Anzeige weiterer Datentypen | Zeit nach Genauigkeit (Tag `2020-05-17`, Monat, Jahr, Jahrzehnt, Jahrhundert, Jahrtausend; v. Chr. mit „BCE“, Julianischer Kalender mit „(Julian)“), Quantity mit `±`, wenn die Grenzen symmetrisch sind, Einheit als Entität verlinkt, Monolingual Text mit Sprachkürzel, `somevalue` als „unbekannter Wert“, `novalue` als „kein Wert“, Ränge `preferred` und `deprecated` als Marke | Vorschlag |
| External-ID | Link über die Formatter-URL (`$1` wird mit `rawurlencode`-artigem Quoting ersetzt, `formatter_property`); ohne Formatter-URL steht der Wert als Text | Vorschlag |
| Commons-Bild | `<img>` mit `Special:FilePath/<Name>?width=400` (Leerzeichen werden zu Unterstrichen), `loading="lazy"`, Link auf die Commons-Dateiseite in einem neuen Tab | Vorschlag |
| Verwendet von | Jede Seite listet in einem aufklappbaren Block die Entitäten der Daten, die auf sie als Wert oder als Property zeigen (ohne sich selbst) | Vorschlag |
| Entitätswert außerhalb der Daten | Verweis auf `https://www.wikidata.org/wiki/<ID>` in einem neuen Tab, Anzeige der ID (bisher kein Fall in den Echtdaten) | Vorschlag |
| Veraltete Seiten | `build` löscht eine Seite `docs/Q123.html` oder `docs/P1.html`, wenn die Entität nicht mehr in den Daten ist; andere Dateien in `docs/` bleiben | Vorschlag |
| Linkcheck | `build` liest die geschriebenen Seiten zurück und prüft jedes `href`/`src` ohne Schema (ohne Fragment und Query) auf eine vorhandene Datei in `docs/`; tote Links sind `WARN` | Vorschlag |
| Lizenz, Standard | Ohne `license` in `site.yaml` steht in der Fußzeile **CC0 1.0** (Public Domain) mit Link auf `https://creativecommons.org/publicdomain/zero/1.0/`. Eine andere Lizenz kommt als `license.name` (Text) und optional `license.url` in `site.yaml`; nur `name` wird als Text gezeigt, nur `url` als Link mit der URL als Text. Der Bericht nennt „(default)“, wenn der Standard gilt. Ob Wikibase Cloud selbst CC0 vorschreibt, ließ sich nicht an den Hosting-Seiten bestätigen (Teil D) | 2026-10-20 (Beschluss Florian) |
| Logo und Seitenleiste | Das Logo steht oben links in einer Seitenleiste (höchstens 9 rem), darunter die Links Startseite, Items und Properties; ohne Logo steht dort der Titel als Text. `logo` ist eine Datei im Repository (wird nach `docs/assets/logo/` kopiert, das hält A2, Eigenschaft 2 ein) oder eine URL (dann lädt jede Seite das Bild von dort); auf kleinen Bildschirmen rutscht die Leiste über den Inhalt | 2026-10-20 (Wunsch Florian) |
| Interne Links mit ID | Jeder interne Link zeigt Label und ID: `Archaeological Site (Q10)`, ebenso Properties vor Werten, in Qualifiern und Referenzen, in „Verwendet von“ und in der Überschrift. Die Startseite hat eine eigene ID-Spalte und zeigt im Link nur das Label; eine Entität ohne Label erscheint nur als ID, nicht doppelt | 2026-10-20 (Wunsch Florian) |
| Wikibase-Look (S3b) | Eine Box je Property: links eine schattierte Spalte mit Label und ID, rechts die Statements. Jedes Statement hat ein Rangzeichen (zwei Punkte, bei `preferred` in der Akzentfarbe, bei `deprecated` rot; Titel „Rank: …“), den Wert (bei `preferred` und `deprecated` zusätzlich eine Marke), die Qualifier als zweispaltiges Raster (Label links, Wert rechts) und darunter den Beleg-Schalter. Der Schalter heißt „N references“ / „Eine Fundstelle“ / „N Fundstellen“ und klappt die Belege auf; ohne Belege steht „0 references“ / „0 Fundstellen“ ohne Aufklappen, wie in der echten Wikibase. Die Überschrift läuft über die ganze Breite, die Inhalte sind höchstens 56 rem breit | 2026-10-21 (Wunsch Florian) |
| Sprachtabelle | Unter der Überschrift steht aufgeklappt „In other languages“ / „In weiteren Sprachen“ mit den Spalten Sprache, Bezeichnung, Beschreibung, Auch bekannt als. Zeilen: Standardsprache und zweite Sprache immer, dazu jede weitere Sprache, in der die Entität Label, Beschreibung oder Alias hat (nach Code sortiert). Fehlendes steht als „No label defined“ / „Keine Bezeichnung vorhanden“ (entsprechend bei der Beschreibung); Aliase sind mit ` \| ` verbunden. Sprachnamen kommen aus einer kleinen Tabelle (Englisch, Deutsch und gängige weitere), ein unbekannter Code steht als Code. Die Tabelle ersetzt den früheren Absatz „Auch bekannt als“ | 2026-10-21 (Wunsch Florian) |
| Reiter und Werkzeuge | Reiter links: „Item“, „Property“ oder auf der Startseite „Home“; rechts „Read“ (aktuell) und „Original“ (Link auf die Konzept-URI `<Quelle>/entity/<ID>` in neuem Tab, nur mit Quelle). Der Sprachumschalter sitzt rechts in der Reiterzeile, dort hat Wikibase das Suchfeld, und dort sitzt es seit S5 vor dem Umschalter. In der Seitenleiste folgt unter Logo und Navigation der Abschnitt „Tools“ / „Werkzeuge“ mit „Referenced by“ / „Verwendet von“ als Sprung zum Block `#incoming`, nur wenn etwas auf die Seite zeigt. Die Fußzeile steht am Ende der Inhaltsspalte; die Seitenleiste ist grau, der Inhalt weiß | 2026-10-21 (Wunsch Florian) |
| Logo von `fuzzy-sl` | `assets/logo.jpg` im Demo-Repo (1000 × 1000 Pixel, JPEG, 303 KB, unverändert von Florian geliefert 2026-10-21), `logo: assets/logo.jpg` in `site.yaml`; es wird nach `docs/assets/logo/` kopiert. Ein Logo mit deckend weißem Hintergrund fügt sich über `mix-blend-mode: multiply` in die graue Leiste ein | 2026-10-21 |
| CI im Paket-Repo | `.github/workflows/ci.yml`: Tests (`python -m unittest discover -s tests`) auf Ubuntu mit Python 3.10 und 3.13 sowie Windows mit 3.13, dazu `python main.py --strict` zweimal, nach jedem Lauf muss `git status --porcelain` leer sein. Der eingecheckte `dist/pipeline_report.txt` ist damit mitgeprüft (Befund 13) | 2026-10-21 (bestätigt mit S8) |
| Workflow für Site-Repos | wiederverwendbar (`workflow_call`) in `.github/workflows/site.yml`. Eingaben: `requirements` (Standard `requirements.txt`), `command` (Standard `python main.py --strict`), `python-version`, `deploy` (Standard `true`). Job `check`: Lauf 1, Baum sauber, Lauf 2, Baum sauber. Job `deploy`: nur nach `check`, nur auf dem Standard-Branch, nie bei Pull Requests. Die Eingaben gehen über `env` in die Shell, nie in eine `run`-Zeile | 2026-10-21 (bestätigt mit S8) |
| Aufrufer im Site-Repo | `examples/site-caller.yml`; der aufrufende Job braucht `contents: read`, `pages: write`, `id-token: write`. Das Template (S9) legt ihn gleich mit an | 2026-10-21 (bestätigt mit S8) |
| Pages-Quelle | „GitHub Actions“ statt Branch `main`, Ordner `/docs`. Veröffentlicht wird der eingecheckte Ordner `docs/`, nachdem `check` gezeigt hat, dass er einem frischen Bau entspricht. Löst die frühere Annahme (Teil D) ab | 2026-10-21 (bestätigt mit S8) |
| Versionen der Actions | Tags der Hauptversion: `actions/checkout@v6`, `actions/setup-python@v6`, `actions/configure-pages@v5`, `actions/upload-pages-artifact@v4`, `actions/deploy-pages@v4` (Pages-Doku, geprüft 2026-10-21). Von `checkout` und `setup-python` gibt es auch v7; nicht eingesetzt, weil die Doku v6 zeigt und die Pages-Actions dort nicht dazugehören. `tests/test_ci.py` verlangt Tags der Hauptversion Lauf #2 und der Lauf im Demo-Repo waren grün; GitHub meldet, dass `configure-pages@v5`, `deploy-pages@v4` und die Upload-Action noch auf Node.js 20 zielen und auf Node 24 gezwungen werden (Teil D). | 2026-10-21 (bestätigt mit S8) |
| Prüfung ohne Workflow-Logik | Jede Prüfung, die CI macht, läuft auch lokal (Schritte als `WARN`, Gate über `git status`); `tests/test_ci.py` führt dieselben Befehle gegen ein temporäres Site-Repo aus und prüft, dass die Workflow-Dateien sie noch enthalten | 2026-10-21 (bestätigt mit S8) |
| Wrapper im Demo-Repo bis S9 | `main.py` des Demo-Repos nimmt `--strict` als erstes Argument, zählt `WARN`-Zeilen der Schritte und gibt dann Exit 1 (wie `main.py` hier) und führt `load` im Standardlauf; die Logik steht vorläufig doppelt und entfällt mit dem Orchestrator im Paket (S9, Zeile „Orchestrator im Paket“) | 2026-10-21 (bestätigt mit S8) |
| CSV, Quelle der Wahrheit (S7) | Für die CSV-Variante ist `data/csv/` die einzige von Hand bearbeitete Quelle; `data/derived/` (Wikibase-JSON) ist Produkt. Vier Tabellen: `entities.csv` (`id, kind, datatype, origin, label_<lang>, description_<lang>, aliases_<lang>`; `origin` leer bei Handarbeit, sonst `open-archaeo`, `wikidata` oder `wikidata-stub`; `kind` = `class`, `property`, `item`; Sprachspalten beliebig erweiterbar), `statements.csv` (`sid, subject, property, value, rank, origin`), `qualifiers.csv` (`sid, property, value`), `references.csv` (`sid, group, property, value`). `sid` braucht nur ein Statement mit Qualifiern oder Belegen. `origin` bleibt bei Handarbeit leer. Die Property bestimmt, wie `value` gelesen wird (wie in Wikibase) | 2026-10-21 (Wahl „vier Tabellen“ von Florian bestätigt, Ergänzung um den Update-Kanal in der nächsten Zeile ist Vorschlag) |
| CSV, Wertsyntax | Item und Property als ID; String, URL, External-ID und Commons-Datei als Text; Koordinate `lat,lon` (Dezimalgrad); Zeit `2021`, `2021-06`, `2021-06-04` (Genauigkeit aus der Länge, v. Chr. mit Minus); Menge `12` oder `12 Q<Einheit>`; Monolingual `de:Text`; `?` = unbekannter Wert, `-` = kein Wert. Ein Wertcodec im Paket liest und schreibt diese Form und die der QuickStatements-Zeilen (Zeile „Update-Kanal“); Zeilenfehler melden `datei:zeile` | Vorschlag 2026-10-21 (S7a) |
| CSV, Update-Kanal | Anregung von Florian am 2026-10-21: Für den ersten Bestand CSV, für spätere Änderungen etwas wie QuickStatements. Entscheidung: **CSV bleibt der Zustand, QuickStatements ist die Änderungssprache.** `python main.py apply-qs <Datei>` liest eine `.qs`-Datei (Teilmenge von QuickStatements v1 in der Schreibweise von `wbqs`, Befund 37) mit ausdrücklichen lokalen IDs, schreibt die Änderungen in die CSV und legt Datei und Hash in `data/edits/applied.csv` ab; dieselbe Datei wirkt kein zweites Mal. Gründe: dieselbe Datei geht später in eine echte Wikibase, die Pack-Beispiele (`alligator.qs`) und der Importer in `wikibase-federation` sprechen schon so, und es gibt „Entfernen“, was eine CSV-Zeile nicht kann. Verworfen: die `.qs`-Dateien als Ereignisprotokoll zu behalten und beim Bau abzuspielen (dann gäbe es zwei Quellen und kein lesbares Bild des Zustands) | Vorschlag 2026-10-21 (S7e) |
| CSV, kanonische Form | `csv-fmt` und der Schreiber der Importer: UTF-8 ohne BOM, LF, Spaltenfolge fest, Zeilen nach ID (Q vor P, numerisch), Anführungszeichen nur wo nötig. Damit gilt die Zwei-Läufe-Regel auch für die Quelle | Vorschlag 2026-10-21 (S7a) |
| Kern (S7) | Immer vorhanden: **Q1 Class** (`instance of` Q1), **Q2 Property** (jede P-Entität ist `instance of` Q2; das Tool erzeugt es aus `kind=property`), **Q3 Instance** (Wurzel des Klassenbaums, `owl:Thing`-artig; jede Klasse hat über `subclass of` einen Weg nach Q3; Items werden über ihre Domänenklasse typisiert), **P1 subclass of**, **P2 instance of**, **P3 subproperty of** (Datentyp `wikibase-property`). Die RDFS-Lesart ist `rdfs:Class`, `rdf:Property`, `owl:Thing` und `rdfs:subClassOf`, `rdf:type`, `rdfs:subPropertyOf` | 2026-10-21 (Q1 bis Q3, P1 bis P3 und die Rolle von Q3 von Florian bestätigt) |
| Kern, Zusatz | **P4 Wikidata equivalent** (external-id, `Q7397` oder `P275`; Schlüssel für Crosswalk und Reimport, ersetzt das String-P15 aus `wikibase-federation`), **P5 formatter URL** (string; für P4 `https://www.wikidata.org/entity/$1`; `formatter_property: P5`), **P6 reference URL** (url), **P7 retrieved** (time), **P8 stated in** (item), **P9 domain** (item, Klasse), **P10 range** (item, Klasse) | 2026-10-21 (alle Zusätze von Florian gewählt; die Nummern sind mein Vorschlag) |
| Kern, Ablage und Nummern | Der Kern liegt als CSV im Paket (`data/kernel/`) und wird von `from-csv` eingemischt; eigene CSV dürfen für Kern-IDs nur Übersetzungen, Aliase und Beschreibungen ergänzen, alles andere ist `WARN`. IDs 1 bis 99 sind für den Kern reserviert, das Domänenmodell beginnt bei 100 (der Kern kann wachsen, ohne dass sich Domänen-IDs ändern) | Vorschlag 2026-10-21 (S7a) |
| Kern, Validierung | `WARN`: Kern unvollständig oder verändert; Klasse ohne Weg nach Q3; Item (`kind=item`) ohne `instance of` auf eine Klasse; Klasse oder Property ohne `instance of` Q1 bzw. Q2 (nach dem Einmischen); Property ohne Datentyp; Aussage, deren Wert gegen `domain` oder `range` der Property verstößt (nur wenn gesetzt, geprüft über `subclass of`) | Vorschlag 2026-10-21 (S7a) |
| RDFS-Brücke | Wenn der Kern vorhanden ist, ergänzt der Schritt `rdf` Tripel `wdt:P1 rdfs:subPropertyOf rdfs:subClassOf`, `wdt:P2 rdfs:subPropertyOf rdf:type`, `wdt:P3 rdfs:subPropertyOf rdfs:subPropertyOf` und `wd:Q1 owl:equivalentClass rdfs:Class`, `wd:Q2 owl:equivalentClass rdf:Property`, `wd:Q3 owl:equivalentClass owl:Thing`. Der Abschnitt steht in der Datei klar gekennzeichnet; ohne Kern entsteht nichts. Die Wirkung auf die Standardabfragen ist zu prüfen (S7b) | Vorschlag 2026-10-21 (S7b; Bedarf von Florian bestätigt) |
| Importer schreiben in die CSV | Importer (open-archaeo, Wikidata) schreiben Zeilen in `data/csv/` mit `origin=open-archaeo` bzw. `origin=wikidata`, nie direkt nach `data/derived/`. Ein Reimport ersetzt nur Zeilen mit diesem `origin` für die betroffenen Subjekte; wer eine Zeile dauerhaft ändert, leert den `origin`-Wert, dann gilt sie als von Hand. Jede Importzeile trägt einen Beleg (P6 reference URL, P7 retrieved, bei Wikidata P8) | Vorschlag 2026-10-21 (S7c, S7d) |
| IDs der Importer | `data/csv/idmap.csv` (`source, key, id`) hält die Zuordnung Quellschlüssel → lokale ID fest (open-archaeo-ID `5700bb`, Wikidata-Q-ID, GitHub-Name); neue IDs sind die nächste freie Nummer ab 100 je Typ, nie wiederverwendet, auch nach einer Löschung nicht. Die Datei ist versioniert | Vorschlag 2026-10-21 (S7c) |
| Wikidata-Import | Seeds in `data/csv/seeds-wikidata.csv` (`qid, kind, note`); Abruf per `wbgetentities` (Batches zu 50, Client und Höflichkeitsregeln wie `harvest`), Roh-JSON unverändert in `data/raw/wikidata/`, `lastrevid` in dessen Manifest, nur Geändertes wird neu geholt. Properties werden über `wikidata_pid` im Modell zugeordnet; nicht zugeordnete erscheinen im Lückenbericht (Zahl und Liste), nicht in den Daten. Item-Werte: hat das Ziel einen lokalen Zwilling (P4), wird dessen ID benutzt, sonst entsteht ein Stub (Label, Beschreibung, P4) bis Tiefe 1; kein Wert enthält je eine fremde ID (Befund 34). „Retrieved“ ist das `modified` der Revision, nicht die Uhr (A3) | Vorschlag 2026-10-21 (S7d) |
| open-archaeo-Import | Eingabe `data/raw/open-archaeo-software.csv` (Kopie der Ausgabe von `py/transform.py`, A3), Zuordnung `data/csv/mapping/open-archaeo.csv` (aus dem Pack, Spalten `column, property, qualifiers, rule`); Regeln wie `pipe-split`, `platform_role`-Auswahl und Registry-Auswahl stehen in der Zuordnung, nicht im Code. Offline, kein Teil des Standardlaufs (schreibt Quelldateien). Tags werden Vokabular-Items, Autoren Personen-Items; Abgleich mit Wikidata folgt über die Seeds | Vorschlag 2026-10-21 (S7c) |
| Startumfang Chublets | Ausschnitt von etwa 100 Einträgen der 416 Software-Einträge (Parameter `--limit` oder `split.py`-Ausschnitt, die Wahl fällt in S7c); erst die Messung (Tripelzahl, Laufzeit der Abfragen im Browser), dann der volle Bestand | 2026-10-21 (von Florian gewählt) |
| Reihenfolge S7 | S7a Kern, CSV, `from-csv`, `to-csv`, `csv-fmt`; S7b Modell und Demo-Repo; S7c open-archaeo; S7d Wikidata; S7e `apply-qs`; S7f Reiter „Source rows“; S7g Push in die echte Wikibase (Repo `wikibase-federation`). Je Schritt ein Chat. Die Aufteilung ersetzt die Fünfteilung aus dem Konzeptentwurf im Chat (dort war „Source rows“ S7e) | 2026-10-21 |
| Zwei Ziele aus einer CSV | Anlass: Florian am 2026-10-21, die reale Wikibase `https://chublets-wikibase.de` (mit Federation) soll mit einem ähnlichen Prozess gefüllt werden. Die CSV in `data/csv/` ist die gemeinsame Quelle für (a) die statische Seite (dieses Repo, `from-csv`) und (b) die echte Wikibase (S7g). `data/derived/` ist die Schnittstelle zwischen beiden | 2026-10-21 |
| Push-Weg | Wikibase-JSON per `wbeditentity`, als Schritt im Repo `wikibase-federation` (Anmeldedaten bleiben dort in der nicht eingecheckten `config.ini`; `wikibase-static` bekommt keinen Schreibzugriff). Liest `data/derived/entities/*.json` des Demo-Repos, zwei Durchläufe (erst Entitäten anlegen, dann Aussagen mit zugeordneten IDs), idempotent (vorhandene Aussagen werden über Property, Wert und Qualifier erkannt und übersprungen), Trockenlauf ist der Standard. Verworfen: den QS-Dialekt von `wbqs` um Qualifier, Belege, Labels und Zeit zu erweitern (mehr Arbeit im zweiten Repo, und das JSON trägt alles schon) | 2026-10-21 (Wahl von Florian; Einzelheiten Vorschlag, S7g) |
| Ziel-Wikibase, IDs | `chublets-wikibase.de` gilt als leer oder frisch (Angabe Florian 2026-10-21, ungeprüft). Der Push legt zuerst den Kern an (Items Q1 bis Q3, Properties P1 bis P10, je Typ in dieser Reihenfolge) und bricht ab, wenn eine vergebene ID von der CSV abweicht. Alle übrigen IDs vergibt die Wikibase; die Zuordnung CSV-ID → Ziel-ID steht in `idmap-<ziel>.csv` im Usecase-Ordner. Die statische Demo zeigt deshalb die CSV-IDs, die echte Wikibase ihre eigenen (Teil D) | Vorschlag 2026-10-21 (S7g) |
| Wikidata-Werte beim Push | Stub in der CSV (`origin=wikidata-stub`, P4 trägt die Wikidata-ID); beim Push wird daraus der Wert `http://www.wikidata.org/entity/Q…` aus P4, der Stub entsteht in der Ziel-Wikibase nicht. Schalter je Ziel `values: federated` (Standard) oder `local` (Stubs werden dann wie Items angelegt). Ein in der CSV von Hand geschriebenes `wd:Q…` ist ebenfalls föderiert | 2026-10-21 (Wahl von Florian; Schalter Vorschlag) |
| Properties beim Push | Nur lokal; P4 dokumentiert die Zuordnung an der Property, es entstehen keine Aussagen mit `wd:P…` (kein `local+federated`); der Schalter kann später dazukommen. Der Datentyp `url` fällt beim Push auf `string` zurück, wenn die Ziel-Wikibase ihn sperrt (Schalter `url_as_string`, wie auf der Instanz des Software-Usecases) | 2026-10-21 (Wahl von Florian: nur lokal; `url_as_string` Vorschlag) |

### A5 Was in welchem Chat hochgeladen wird

Ein Bundle statt Einzeldateien. Mitnehmen: `PRIMER.md`, Quelltexte, kleine Daten. Nicht mitnehmen: `.git/`, `.venv/`, `config.local.*`, große erzeugte Dateien.

```cmd
robocopy . ..\wikibase-static-bundle /E /XD .git .venv __pycache__ build /XF config.local.ini config.local.json >nul & powershell -NoProfile -Command "Compress-Archive -Path ..\wikibase-static-bundle\* -DestinationPath ..\wikibase-static-bundle.zip -Force"
```

(robocopy meldet Erfolg mit Exit-Code unter 8, das ist normal.) Für S7b und S7c zusätzlich `chublets-wikibase-starter-pack.zip` (Quelle des Modells, Befund 32) und ein Klon von `open-archaeo` (`open-archaeo-software.csv`, Befund 33), das Bundle des Demo-Repos erst ab S7b. Für S4 zusätzlich ein paar im Browser gesicherte JSON-Dateien aus `fuzzy-sl`, falls Anubis den Abruf blockiert.

### A6 IRI-Landkarte

Das Repo veröffentlicht RDF (S6). Die RDF-Dateien verwenden die Konzept-URIs der Quell-Wikibase (z. B. `https://fuzzy-sl.wikibase.cloud/entity/Q1`), damit dieselben Queries wie gegen die echte Wikibase laufen (umgesetzt 2026-10-21, A4 „RDF, Basis-URI“). Bei der Dummy-Wikibase kommt die Basis aus `site.yaml` (`rdf_base`).

| Pfad | Inhalt | Ziel des Redirects | Status |
|---|---|---|---|
| `dist/<host>.ttl` | RDF aller Entitäten im Wikibase-Modell, beschrieben mit DCAT 3 | – (versioniert im Repo) | umgesetzt 2026-10-21 |
| `docs/downloads/<host>.ttl` | dieselbe Datei, veröffentlicht | – (Datei auf Pages) | umgesetzt 2026-10-21 |
| `docs/ttl/<ID>.ttl`, `docs/json/<ID>.json` | eine Entität als Turtle bzw. wie archiviert (Distributions des Datasets `data:<ID>`) | – (Dateien auf Pages) | umgesetzt 2026-10-21 |
| `docs/downloads/wikibase-ontology.ttl` | Wikibase-Systemontologie | – | umgesetzt 2026-10-21 |
| `docs/sparql.html`, `docs/downloads/queries/<id>.rq` | Query-Seite im Browser und die Abfragen als Dateien | – | umgesetzt 2026-10-21 |
| `<base>/catalog`, `<base>/catalog/items|properties|export|wikibase-ontology`, `<base>/distribution/<ID>-json|ttl|html` | IRIs der DCAT-Knoten im Namensraum der Quell-Wikibase (nicht von ihr aufgelöst) | keiner | umgesetzt 2026-10-21 |
| w3id-Präfix für die Dummy-Wikibase | offen | offen | geplant |

---

## Teil B — Schrittübersicht

| ID | Schritt | Repo | hängt ab von | Status |
|---|---|---|---|---|
| S0 | Festlegungen: Zwischenformat, `site.yaml`-Schema, Seiten-URLs | wikibase-static | – | erledigt 2026-10-20 |
| S1 | Skeleton: Layout, `main.py`, `utils.py`, Lizenz, Citation | wikibase-static | – | erledigt 2026-10-20 |
| S2 | Loader und Validator für das Zwischenformat, Label-Auflösung | wikibase-static | S0, S1 | erledigt 2026-10-20 |
| S3 | Renderer: Item- und Property-Seiten im Wikibase-Look, Leaflet, Commons, Linkcheck | wikibase-static, fuzzy-sl-static | S2 | erledigt 2026-10-20 (Sichtprobe mit Commons-Bild und Kacheln bei dir offen, Teil D) |
| S3b | Wikibase-Look: Boxen je Property, Sprachtabelle, Reiter, Seitenleiste mit Werkzeugen; Logo im Demo-Repo; Bericht nur für eigene Daten | wikibase-static, fuzzy-sl-static | S3 | erledigt 2026-10-21 |
| S4 | Harvest, inkrementell, `--probe`, `--from-dir`; Test mit `fuzzy-sl` | wikibase-static, fuzzy-sl-static | S0, S1 | erledigt 2026-10-20 |
| S5 | Suche mit Autocomplete | wikibase-static, fuzzy-sl-static | S2 | erledigt 2026-10-21 (Windows und andere Browser als Chromium offen, Teil D) |
| S6 | RDF-Export (mit DCAT 3, Turtle je Entität, Wikibase-Ontologie) und SPARQL-Seite | wikibase-static, fuzzy-sl-static | S2 | erledigt 2026-10-21 (Laden von Pyodide und rdflib im Browser bei dir offen, Teil D) |
| S6b | Abfrage-Editor (`docs/query.html`) wie der Query Service: freies Feld, Tabelle, Karte, Bilder | wikibase-static, fuzzy-sl-static | S6 | erledigt 2026-10-21 (Pyodide und rdflib im Browser bei dir offen, Teil D) |
| S7 | CSV-Import und Chublets-Demo (Sammelschritt, geteilt in S7a bis S7f) | wikibase-static, chublets-wikibase-demo | S2 | Konzept beschlossen 2026-10-21, Code offen |
| S7a | Kern, CSV-Format, `from-csv`, `to-csv`, `csv-fmt`, Wertcodec, Validator | wikibase-static | S2, S4 | offen |
| S7b | Modell aus dem Starter Pack, Demo-Repo `chublets-wikibase-demo`, RDFS-Brücke | wikibase-static, chublets-wikibase-demo | S7a | offen |
| S7c | open-archaeo-Importer (Ausschnitt etwa 100) | wikibase-static, chublets-wikibase-demo | S7b | offen |
| S7d | Wikidata-Importer (`import-wikidata`, Seeds, Lückenbericht) | wikibase-static, chublets-wikibase-demo | S7b | offen |
| S7e | Update-Kanal: `apply-qs` | wikibase-static | S7a | offen |
| S7f | Reiter „Source rows“ auf den Entitätsseiten | wikibase-static | S7a | offen |
| S7g | Push in `chublets-wikibase.de`: `wbeditentity`, `idmap`, Kern zuerst, Trockenlauf | wikibase-federation | S7a, S7b | offen |
| S8 | Pages-Workflow, Determinismus- und Linkcheck in CI | wikibase-static, fuzzy-sl-static | S3 | erledigt 2026-10-21 |
| S9 | Template-Repo `wikibase-static-template` | wikibase-static-template | S3, S8 | offen |
| S10 | Skill aus dem bewährten Repo | – | S9 | offen |

S0 und S1 sind unabhängig voneinander. Nach S2 sind S3, S5, S6 und S7 voneinander unabhängig und können in beliebiger Reihenfolge laufen; S4 braucht nur das Zwischenformat aus S0 und kann schon vor S2 beginnen, weil `data/raw/` nur Rohdaten ablegt. S8 braucht mindestens S3. Ein Chat darf auf S4 starten, auch wenn S2 noch offen ist. Innerhalb von S7 ist S7a die Voraussetzung für alles; danach sind S7e und S7f unabhängig von den Importern, S7c und S7d unabhängig voneinander (beide brauchen das Modell aus S7b). S7g braucht S7a und S7b und läuft im Repo `wikibase-federation`; für den Anfang genügen Kern und Modell, die Importer sind keine Voraussetzung.

---

## Teil C — Die Schritte

### S0 — Festlegungen (kein Code)

**Ziel:** Die Entscheidungen, deren spätere Änderung erzeugte Dateien umschreiben würde, stehen in A4.

**Uploads:** Standard-Bundle.

Als Formular zu klären (jeweils mit freiem Kommentarfeld): Seiten-URL-Schema (`Q123.html` flach oder `item/Q123/`), Inhalt und Schlüssel von `site.yaml` (Titel, Logo, Farben, Basis-URL der Quelle, Standardsprache, zweite Sprache, Impressum), Umgang mit föderierten Properties und Werten (Link auf Wikidata statt eigener Seite), Lizenzhinweis pro Seite (Quelle, Abrufdatum aus dem Manifest, Lizenz der Wikibase).

**Abnahme:** Jede Frage oben hat in A4 einen datierten Beschluss oder ist ausdrücklich als `Vorschlag` markiert.

### Erledigt 2026-10-20

Als Formular beantwortet, alle vier Empfehlungen angenommen (Einzelheiten in A4): flaches URL-Schema, `en` Standard mit `de` als zweiter Sprache, föderierte Verweise nur verlinken, Fußzeile mit Quelle, Stand und Lizenz. Der Schlüsselsatz von `site.yaml` steht als `Vorschlag` in A4 und wird mit S3 bestätigt, sobald der Renderer ihn liest. Dazu kamen zwei Beschlüsse zum Demo-Repo und zum Orchestrator (A4, Befund 8). Offen bleibt die Lizenz von `fuzzy-sl` (Teil D); die Fußzeile zeigt bis dahin „Lizenz nicht angegeben“.

### S1 — Skeleton

**Ziel:** Ein lauffähiges Gerüst nach dem Muster der Familie, in dem jeder Schritt „nothing to do“ meldet.

**Uploads:** keine; das Repo ist leer angelegt.

Inhalt: `main.py` mit den Flags `--list`, `--only`, `--from`, `--skip`, `--dry-run`, `--strict` und dem Verb `harvest`; Paket `py/wikibase_static/` mit `utils.py` und je einem Modul pro Schritt; `pyproject.toml`, `requirements.txt`, `LICENSE`, `CITATION.cff`, `.gitignore` (ignoriert `dist/` und `docs/` bewusst nicht), `README.md`, dieses Primer.

**Abnahme:**

1. `python main.py --list` nennt alle Schritte (ab S2 sieben), `harvest` als Verb.
2. `python main.py` meldet für jeden Standardschritt „nothing to do“ und endet mit Exit-Code 0; `python main.py --strict` ebenso.
3. Zwei Läufe hintereinander, danach `git status`: sauber (nach dem ersten Commit von `dist/pipeline_report.txt`).
4. `python main.py harvest` läuft nur diesen Schritt.

### S2 — Zwischenformat, Loader, Validator

**Ziel:** Ein Modul liest `data/raw/` und `data/derived/` in ein internes Modell und prüft es.

Inhalt: Items und Properties aus Wikibase-JSON, Labels, Descriptions, Aliases, Claims mit Qualifiers und References, Datentypen aus A4. Label-Auflösung für referenzierte Entitäten (Cache nach dem Muster von `labels.py`). Validator meldet fehlende Referenzen als `WARN`.

**Abnahme:** Eine Beispieldatei je Datentyp wird gelesen; der Bericht nennt Zahl der Items, Properties und Claims; ein absichtlich kaputtes JSON erzeugt eine Warnung, keinen Absturz.

### Erledigt 2026-10-20

**Gebaut:** `py/wikibase_static/model.py` (Dataclasses `Entity`, `Statement`, `Snak`, Datentypen aus A4), `loader.py` (`load_site()`, Validator, `LabelResolver`), `step_load.py` (Bericht), Eintrag `load` in `main.py`; `tests/test_loader.py` mit `tests/fixtures/entities/` (je eine Property pro Datentyp, ein Item `Q1` mit einem Statement pro Datentyp, dazu `Q2`). Die Entscheidungen stehen als `Vorschlag` in A4.

**Befunde:**

- 24 Tests laufen durch (alle zehn Datentypen, `somevalue`, Qualifier, Reference, Rang, Reihenfolge, `Special:EntityData`-Form, unlesbares JSON, fehlende Entität und Property, Datentyp/Wert-Konflikte, Manifest-Abweichung, Doppel- und Dateinamen-Konflikt, Label-Fallback, Bericht und `--strict`-Zeilen, Obergrenze der Warnungen). Die zehn Tests des Harvest laufen unverändert weiter.
- **Gegen die echten Daten** (`fuzzy-sl-static`, Commit `896b173`): 173 Entitäten (137 Items, 36 Properties), 488 Statements (`wikibase-item` 293, `url` 79, `globe-coordinate` 62, `string` 51, `external-id` 3), **0 Warnungen**. Das heißt: Keine der ID-Lücken aus Befund 7 (Q8, Q9, …, P36) wird irgendwo referenziert, jede Referenz löst auf. Zwei Läufe liefern den identischen Bericht.
- Beschädigte Kopie der Echtdaten (eine Datei kaputt, eine gelöscht): fünf `WARN`-Zeilen, der Lauf bricht nicht ab, `--strict` endet mit Exit-Code 1.
- Die Auflösung von Labels braucht kein Netz und keinen Cache auf der Platte: Alle Entitäten, auf die `fuzzy-sl` verweist, liegen in den Daten (Befund oben). Ein Disk-Cache nach dem Muster von `labels.py` wird erst nötig, wenn eine Wikibase auf fremde IDs verweist (föderierte Werte werden nur verlinkt, A4).
- Der Standardlauf im Paket-Repo ohne Daten bleibt „nothing to do“ (`--strict` Exit-Code 0); `dist/pipeline_report.txt` bekommt dafür die Zeilen des neuen Schritts.

### S3 — Renderer

**Ziel:** `docs/` enthält für jede Entität eine Seite im Wikibase-Look.

Inhalt: Jinja2-Templates und ein CSS, Startseite aus `site.yaml`, Statements mit Qualifiern und References, interne Links, externe Links mit `target="_blank" rel="noopener"`, External-IDs über die Formatter-URL, Leaflet für Koordinaten, Commons-Bilder über `Special:FilePath`.

**Abnahme:** Entitätenzahl gleich Seitenzahl; Linkcheck mit 0 toten internen Links; zwei Läufe, `git status` sauber; eine Seite mit Koordinate und Bild im Browser angesehen.

### Erledigt 2026-10-20 (Code, Tests, Lauf gegen `fuzzy-sl`)

**Gebaut:** `py/wikibase_static/site_config.py` (liest und prüft `site.yaml`, Standardlizenz CC0), `render.py` (reine Funktionen von Modell und Konfiguration zu HTML-Teilen: Werte, Statements, Fußzeile, „Verwendet von“), `step_build.py` (Seiten schreiben, Assets kopieren, veraltete Seiten löschen, Linkcheck), `templates/` (`base` mit Seitenleiste für Logo und Navigation, `index`, `entity`, `_macros`), `static/` (`style.css`, `app.js`, `map.js`, Leaflet 1.9.4), `tests/test_build.py`; `pyproject.toml` (Abhängigkeiten PyYAML und Jinja2, Paketdaten), `requirements.txt`, `README.md`. Im Demo-Repo kommen `site.yaml` und der Hinweis zu `build` im README dazu. Die Entscheidungen stehen in A4 als `Vorschlag`, der Schlüsselsatz von `site.yaml` ist bestätigt.

**Befunde:**

- 39 Tests laufen durch (Formatierung aller Datentypen nach Genauigkeit, `site.yaml` mit gültigen und ungültigen Werten, Seiten je Entität, Karte nur bei Erdkoordinaten, `javascript:`-URL wird kein Link, HTML-Escaping von Label und Wert, External-ID mit Formatter-URL, Wikidata-Link für fremde IDs, Sprachumschalter und Einzeltext bei gleichem Wortlaut, Fußzeile mit Standardlizenz CC0, eigener Lizenz, nur Text und nur URL, Q-/P-ID hinter jedem internen Link (auch ohne Label nicht doppelt), Seitenleiste mit Navigation, „Verwendet von“, Logo im und außerhalb des Repos, zwei Läufe byte-gleich ohne CRLF in Text-Assets, veraltete Seiten, leeres Repo, Linkcheck mit Fragment, Mail, Schema, `..` und URL-Dekodierung, `WARN` bei totem Link). Die 24 Tests des Loaders und die 10 des Harvests laufen unverändert.
- **Gegen die echten Daten** (`fuzzy-sl-static`, Commit `e0856b8`, mit dem `site.yaml` aus dem Patch): `173 entities -> 173 entity pages + index.html (difference 0)`, `4733 internal links checked, 0 dead`, 61 verschiedene Koordinaten auf 59 Seiten (Befund 12), 0 `WARN`. Zwei Läufe liefern byte-gleiche Dateien; nach `git commit` der Seiten und einem zweiten `python main.py build` ist `git status` sauber (geprüft über den `main.py`-Wrapper mit dem aus dem Paket-Verzeichnis frisch in eine neue virtuelle Umgebung installierten Paket, das ist der Weg des Demo-Repos).
- `pip install` des Pakets liefert Templates, CSS, JS und Leaflet mit (Paketdaten in `pyproject.toml`, geprüft an der installierten Kopie).
- Im Browser angesehen (Chromium ohne Netz, Screenshots): `Q46`, `Q74`, `Q97` (mit einem Platzhalter-Logo; das echte Logo von `fuzzy-sl` liegt nicht in den Rohdaten und muss als Datei ins Demo-Repo) und die Fixture `Q1`. Karte mit Markern, Sprachumschalter (EN/DE), Rangmarke, Qualifier, aufklappbarer Beleg, External-ID über P18 verlinkt, zwei Marker bei Q74. **Nicht gesehen:** Kartenkacheln und ein echtes Commons-Bild, denn die Sandbox erreicht beide Hosts nicht (das Bild erscheint nur als Alt-Text); die Echtdaten von `fuzzy-sl` enthalten kein Bild (Befund 7). Der Standardlauf im Paket-Repo ohne Daten bleibt „nothing to do“, `--strict` endet mit Exit-Code 0; `dist/pipeline_report.txt` ändert sich dafür in der Zeile von `build`.
- Der eingecheckte `dist/pipeline_report.txt` (Commit `4684ce4`) zeigte noch einen Lauf mit den 173 Entitäten von `fuzzy-sl`, obwohl `data/raw/` des Paket-Repos leer ist (A3). Ein Lauf ohne Daten schreibt ihn auf „nothing to do“ zurück; das ist die richtige Fassung und kommt mit diesem Stand in den Commit.
- Zeit-, Quantity-, Monolingual- und Commons-Werte sind nur an den Fixtures geprüft, nicht an echten Daten (die gibt es in `fuzzy-sl` nicht).

### S3b — Wikibase-Look

**Ziel:** Die Seiten sehen aus wie eine echte Wikibase: Seitenleiste mit Logo, Reiter, Sprachtabelle und je Property eine Box mit Statements, Qualifiern und Beleg-Schalter.

**Uploads:** der Screenshot einer Originalseite (`Q97` von `fuzzy-sl`) und das Logo.

Inhalt: neues `base.html` (Seitenleiste, Reiterzeile, Fußzeile in der Inhaltsspalte), `entity.html` (Sprachtabelle, Boxen, Raster für Qualifier und Belege), `style.css` neu; in `render.py` Pluralformen („1 reference“, „Eine Fundstelle“), `language_rows()` und Rang-Titel, die Methode `aliases()` entfällt; in `step_build.py` die neuen Kontextwerte. Dazu `main.py`: Bericht nur für eigene Daten (Befund 13, A3), `tests/test_main.py`. Im Demo-Repo `assets/logo.jpg` und `logo:` in `site.yaml`. Die Entscheidungen stehen in A4 (Zeilen „Wikibase-Look (S3b)“, „Sprachtabelle“, „Reiter und Werkzeuge“, „Logo von `fuzzy-sl`“).

**Abnahme:** Entitätenzahl gleich Seitenzahl; 0 tote interne Links; zwei Läufe, `git status` sauber; `Q97` im Browser neben dem Original: Seitenleiste mit Logo oben links, Reiter, Sprachtabelle, eine Box je Property, Qualifier-Raster, „0 Fundstellen“; ein Lauf im Paket-Repo mit gesetztem `WBS_ROOT` lässt `dist/pipeline_report.txt` unberührt.

### Erledigt 2026-10-21

**Gebaut:** wie unter Inhalt. Das Muster der Boxen, der Sprachtabelle und des Beleg-Schalters stammt aus dem Screenshot von `Q97` (Wikibase Cloud, deutsche Oberfläche); die Texte sind eigene.

**Befunde:**

- 48 Tests in `tests/test_build.py` (neu: Plural der Belege in beiden Sprachen, Qualifier und Belege als Label-Wert-Paare, Rangzeichen mit Titel, Sprachtabelle mit Standard-, zweiter und weiteren Sprachen samt Escaping und unbekanntem Code, Reiter mit und ohne Quelle, Werkzeuge nur bei eingehenden Verweisen, Fußzeile in der Inhaltsspalte), 5 in `tests/test_main.py` (zwei davon schlagen mit dem alten `main.py` fehl), die 24 des Loaders und die 10 des Harvests unverändert.
- **Gegen die echten Daten** (`fuzzy-sl-static`, Commit `88f63a9`, mit `assets/logo.jpg`): `173 entities -> 173 entity pages + index.html (difference 0)`, `4907 internal links checked, 0 dead`, 61 Koordinaten auf 59 Seiten, 0 `WARN`. Nach dem Commit der Seiten ist `git status` nach einem zweiten Lauf sauber; das Paket kam dabei aus einer neuen virtuellen Umgebung (`pip install` des frischen Klons).
- Im Browser angesehen (Chromium ohne Netz): `Q97` (EN, und mit 420 Pixel Breite), `Q74` (DE, zwei Koordinaten, Rang `preferred`), `P19` (Property mit Formatter-URL), die Startseite. Das Logo steht oben links, der weiße JPEG-Hintergrund verschwindet in der grauen Leiste.
- `Q97` trägt vier Boxen mit je einem Statement; bei Einträgen mit mehreren Werten (`P10` von `Q74`: vier URLs) stehen die Statements untereinander in einer Box.
- **Nicht gesehen:** Kartenkacheln und Commons-Bilder (die Sandbox erreicht beide Hosts nicht), Windows und andere Browser als Chromium.
- Nicht übernommen aus dem Original, weil statisch oder noch ohne Daten: Anmelden, Bearbeiten, Diskussion, Versionsgeschichte, Spracherkennung („Englisch“ hinter jedem Label), die Wikibase-Werkzeuge der Seitenleiste (Neues Item, Query Service, QuickStatements) und das Suchfeld (S5).

### S4 — Harvest

**Ziel:** `python main.py harvest` sichert `fuzzy-sl` nach `data/raw/` und lädt beim zweiten Lauf nichts nach.

Inhalt: Client (aus `wbqs/client.py` übernommen, nur lesend), ID-Liste, `lastrevid`-Vergleich mit `manifest.json`, Löschungen erkennen, `--probe` (ein Testrequest, meldet Anubis klar), `--from-dir` (Roh-JSON aus einem Ordner einlesen), optional `--source sparql`.

**Uploads:** ggf. im Browser gesicherte JSON-Dateien aus `fuzzy-sl`.

**Abnahme:** Erster Lauf füllt `data/raw/`, zweiter Lauf meldet „0 changed“ und schreibt nichts (`git status` sauber); der Bericht nennt die Zahl der Requests.

### Erledigt 2026-10-20 (Code, Offline-Tests, Erst- und Zweitlauf gegen `fuzzy-sl`)

**Gebaut** (`py/wikibase_static/step_harvest.py`, `tests/test_harvest.py`):

- `python main.py harvest --url <Wikibase>`: findet `api.php` (`<url>/w/api.php`, dann `<url>/api.php`; `--api` überschreibt), liest die Namespaces per `meta=siteinfo` (Inhaltsmodell `wikibase-item` bzw. `wikibase-property`) und merkt Quelle, API-Adresse und Namespaces im Manifest. Ab dem zweiten Lauf entfällt die Suche (`--rediscover` erzwingt sie).
- Listen, vergleichen, nur Geändertes laden, Gelöschtes entfernen, wie in A4. Eine von Hand geänderte Datei in `data/raw/entities/` wird erkannt (SHA-256) und neu geladen.
- `--probe`: genau ein Request (`siteinfo`), schreibt nichts, meldet die Namespaces oder die Challenge.
- `--from-dir DIR`: liest gespeicherte JSON-Dateien (`Special:EntityData`-Form, `wbgetentities`-Form oder ein nacktes Entitätsobjekt), kaputte Dateien erzeugen `WARN` und werden übersprungen, nichts wird gelöscht.
- Challenge-Erkennung: Antwort ist kein JSON und enthält Anubis-typische Wörter; dann Abbruch mit Exit-Code 2 und dem Hinweis auf `--from-dir`. Es wird nichts geschrieben.

**Befunde:**

- 10 Tests gegen einen lokalen Fake-Wikibase-Server (Standardbibliothek) laufen durch: Erstlauf, Zweitlauf ohne Änderung (Verzeichnis byte-gleich, nur Listen-Requests, kein `wbgetentities`), geänderte und gelöschte Entität, von Hand geänderte Datei, Challenge, `--probe` (1 Request, nichts geschrieben), `maxlag`-Retry, fremde Quelle, `--from-dir` in drei Formen, kanonisches Dateiformat.
- Bei 7 Entitäten und 2 Entitäten pro Listenseite im Fake braucht der Zweitlauf 4 Requests (nur Liste). Bei 500 pro Seite ist das für dreistellige Größen **ein Request je Namespace**.
- Der Standardlauf (`python main.py`, `--strict`) ist unverändert, `git status` bleibt sauber.
- **Erstlauf gegen `fuzzy-sl`** (bei dir lokal, Ergebnis in `fuzzy-sl-static`): Der Harvest lief über `api.php` ohne Challenge, Titelpräfix, Namespaces und Datenformat entsprachen dem Fake; Details in A1, Befund 7. Die Sandbox selbst erreicht den Host nicht.

- **Zweitlauf gegen `fuzzy-sl`** (bei dir lokal, 2026-10-20): `0 changed, 0 deleted, 173 unchanged (nothing written)`, `requests: 2 (list 2)`, also je eine Listenabfrage pro Namespace und kein `wbgetentities`. Damit stimmt die Seiten-`lastrevid` aus `allpages` mit der `lastrevid` der Entität überein und die Abnahme von S4 ist erfüllt.
- **Zeilenenden:** Der Manifest-Hash gilt für LF-Dateien. Ein Windows-Checkout mit `core.autocrlf=true` macht daraus CRLF, und alle 173 Hashes weichen ab (nachgestellt 2026-10-20 mit einem Klon mit `core.autocrlf=true`); der Harvest würde alles neu laden. Behoben mit einer `.gitattributes` (`* text=auto eol=lf`) in beiden Repos; mit ihr stimmen nach einem solchen Klon alle 173 Hashes.

### S5 — Suche

**Ziel:** Eine Suchbox mit Autocomplete auf jeder Seite.

**Abnahme:** Suche nach einem Label, einem Alias und einer Q-ID findet die Entität; der Index wird deterministisch erzeugt.

### Erledigt 2026-10-21 (Code, Tests, Browserprobe, Lauf gegen `fuzzy-sl`)

**Gebaut:** `static/search.js` (Abgleich als reine Funktionen `normalise`, `prepare`, `search`, `labelFor`; darunter die Bedienung der Seite), `step_search.py` neu (`entry_for`, `build_index`, `render_index`, `term_count`), `model.pick_text` (die Auswahl des Textes nach Sprachliste, von `render._pick` und vom Index gemeinsam genutzt), in `render.py` die Oberflächentexte und `search_texts_json()`, in `base.html` das Formular und das Skript, in `step_build.py` zwei Kontextwerte, in `style.css` die Regeln der Suche samt Eingrenzung der Reiterregeln (Befund 18), `tests/test_search.py`; README beider Repos, Version 0.2.0 (A4). Die Entscheidungen stehen in A4 (Zeilen „Suche …“ und „Version“). Das Demo-Repo bekommt nur die README und das neu gebaute `docs/`; sein Wrapper kannte den Schritt `search` schon.

**Befunde:**

- 140 Tests laufen durch (101 vorher, 39 neu in `tests/test_search.py`): die Rangfolge der Treffer, Label, Alias und ID, Akzente und Groß-/Kleinschreibung, Obergrenze von zehn Treffern, Reihenfolge bei gleichem Rang, Index byte-gleich bei zwei Läufen und unabhängig von der Ladereihenfolge, Maskierung von U+2028/U+2029, `WARN` bei fehlenden Seiten, Formular und Skript auf den Seiten, die beiden CSS-Regressionen (Befunde 18 und 19). Der Abgleich läuft dabei unter Node; ohne `node` werden diese Tests übersprungen (Teil D).
- **Die Tests können rot werden:** neun Mutationen des Abgleichs und des Index, danach zurückgenommen, alle wurden gefangen. Zwei Mutationen überlebten zuerst und deckten Lücken in den Tests auf: unsichtbare Zeichen im Quelltext (Befund 20) und Testdaten, die schon alphabetisch lagen, sodass die Sortierung nach Label nicht auffiel (Q21 „Bastion“ und Q23 „Bastille“: die Ordnung nach Label weicht jetzt von der nach ID ab).
- **Gegen die echten Daten** (`fuzzy-sl-static`, gebaut mit dem lokalen Paket): `173 entities indexed (137 items, 36 properties), 368 searchable strings`, `search-index.js` 27 300 Byte, `173 entities -> 173 entity pages + index.html (difference 0)`, `5081 internal links checked, 0 dead` (vorher 4907; die Seiten verweisen jetzt zusätzlich auf `search.js`), 0 `WARN`. Läufe mit wechselndem `PYTHONHASHSEED` (von Hand, nicht als Test): `docs/` byte-gleich.
- Im Browser geprüft (Chromium ohne Netz, Playwright, 37 von 37 Prüfungen): ein Label, ein Alias und eine Q-ID finden die Entität; Pfeiltasten, Enter, Escape; deutsche Oberfläche nach dem Umschalten; Handybreite (420 Pixel) mit dem Feld in einer eigenen Zeile und ohne Umbruch des Reiters „Item“ (er brach zuerst um, Behebung mit `display: contents`); die Liste über der Karte bei 700 Pixel (Befund 19); die Seite von `file://` geöffnet, die Suche funktioniert; ohne JavaScript bleibt das Feld verborgen; ein fehlender Index wird in der Liste gemeldet; HTML in einem Alias erscheint als Text und läuft nicht.
- **Nicht gesehen:** Windows, andere Browser als Chromium, Kartenkacheln (Sandbox ohne Netz). Der Lauf von `ci.yml` und `site.yml` auf GitHub mit dem neuen Stand steht aus. Der Abruf des Pakets aus GitHub durch das Demo-Repo wurde nur mit einem lokalen Git-Repo als Quelle nachgestellt (Befund 21), das Demo-`docs/` wurde mit einem lokalen Paket gebaut.
- **Reihenfolge beim Einspielen:** erst das Paket-Repo pushen, dann im Demo-Repo `pip install --upgrade -r requirements.txt`, bauen und committen; das CI des Demos installiert das Paket von `main`, ein Demo-Push vor dem Paket-Push wäre rot (`docs/` käme dann aus 0.2.0, das Paket auf `main` wäre 0.1.0).

### S6 — RDF und SPARQL

**Ziel:** `dist/<site>.ttl` im Wikibase-RDF-Modell und `docs/sparql.html` mit Beispielqueries.

**Abnahme:** Jede Beispielquery liefert in der Prüfung mindestens eine Zeile; Turtle ist byte-identisch bei zwei Läufen (sortierte N-Triples als Zwischenschritt).

### Erledigt 2026-10-21 (Code, Tests, Lauf gegen `fuzzy-sl`, Browserprobe mit Pyodide-Attrappe, Abfragen unter echtem Pyodide in Node)

**Gebaut:** `rdf.py` (Terme, Namensräume, Wikibase-Modell, DCAT, Datumsbereinigung, N-Triples, Turtle-Writer), `sparql.py` (Abfragen laden und prüfen, `RUNNER_PY`, `run_all`), `step_rdf.py` und `step_sparql.py` neu (statt der Rümpfe), `data/queries.default.yaml`, `data/wikibase-ontology.ttl`, `templates/sparql.html`, `static/sparql.js` (reine Funktionen oben, Seitenlogik ab `init()`), Regeln in `style.css`, Texte `sq_*` in `render.py` (`sparql_texts()`), Navigationslink und `{% block scripts %}` in `base.html`, in `step_build.py` `page_context()` (der gemeinsame Kontext aller Seiten), `make_env()`, `logo_href()` und `linkcheck(…, pending=)`, in `site_config.py` der Schlüssel `rdf_base`; `pyproject.toml` (rdflib, Paketdaten), `requirements.txt`, Version 0.3.0; `tests/test_rdf.py`, `tests/test_sparql.py`, eine Zeile in `tests/test_build.py`; READMEs beider Repos. Im Demo-Repo: `site.yaml` mit `pages_url`, README, neu gebautes `docs/` und neues `dist/`. Die Entscheidungen stehen in A4 (Zeilen „RDF, …“, „SPARQL, …“, „Version, S6“, „Abhängigkeit `rdflib`“, „`site.yaml`, `rdf_base`“), alle als Vorschlag.

**Befunde:** 22 bis 27 (oben). Dazu:

- 226 Tests laufen durch (140 vorher, 45 neu in `tests/test_rdf.py`, 41 in `tests/test_sparql.py`): Terme und Escapes, Datumsbereinigung (Gregorianisch, v. Chr., Julianisch), Ränge (nur `preferred` ist best, alle `normal`, `deprecated` nie), `novalue`/`somevalue`, Einheiten, Koordinate auf anderem Globus, unbrauchbare Werte als Problem, DCAT (Kataloge, Datasets, Distributions mit URL, ohne `pages_url` keine), Datei je Entität, Byte-Gleichheit über zwei Läufe, unabhängig von Ladereihenfolge und `PYTHONHASHSEED`, natürliche Ordnung; die Abfragen (Standardsatz gültig und zweisprachig, eigene Datei, Fehlerfälle, `requires`, Präfixe, Zeilenobergrenze, Zelltypen), der Schritt am temporären Site-Repo (Dateien, Navigationslink, erster Bau ohne `WARN`, Seiteninhalt, Maskierung, leere und kaputte Abfrage als `WARN`, fehlendes `rdf`, veraltete Kopie, ohne `pages_url`, zwei Läufe byte-gleich, entfernte Entitäten, `rdf_base`) und `sparql.js` unter Node (Maskierung, Verlinkung, Kürzel, Tabellen). Der Standardsatz läuft auch auf der Fixture komplett (11 von 12 Abfragen, `distributions` nur mit `pages_url`).
- **Die Tests können rot werden:** neun Mutationen (bester Rang, `wdt:` für jeden Rang, Jahr v. Chr., Maskierung in `sparql.js`, leere Abfrage, `requires`, Aufräumen alter Dateien, `pending`, Sortierung der N-Triples), alle gefangen; die letzte überlebte zuerst, weil kein Test die Sortierung der N-Triples prüfte, und bekam einen.
- **Gegen die echten Daten** (`fuzzy-sl-static`, gebaut mit dem lokalen Paket): 173 Entitäten, 488 Statements, 12 456 Tripel (6 706 ohne DCAT), 521 Distributions, `dist/fuzzy-sl.wikibase.cloud.ttl` 623 879 Byte, vom Turtle gelesen dieselben 12 456 Tripel; 12 Abfragen mit 137, 36, 18, 22, 200, 20, 60, 13, 44, 24, 3 und 100 Zeilen; `python main.py --strict` Exit 0 ohne `WARN`; ein zweiter Lauf mit anderem `PYTHONHASHSEED` lässt `docs/` und `dist/` byte-gleich (551 Dateien). Im Paket-Repo ändert sich nur `dist/pipeline_report.txt` (zwei Zeilen: „nothing to do“ statt „not implemented yet“).
- **Nicht gesehen:** Laden von Pyodide und `micropip`-Installation im Browser (Befund 26), Windows und andere Browser als Chromium, der Lauf von `ci.yml` und `site.yml` auf GitHub mit dem neuen Stand; ein Vergleich mit dem Query Service der echten Wikibase.
- **Reihenfolge beim Einspielen:** erst das Paket-Repo (Tests, `dist/pipeline_report.txt`), pushen; dann im Demo-Repo `pip install --upgrade -r requirements.txt` (0.3.0), `python main.py --strict` und alles committen (das CI des Demos installiert das Paket von `main`). Ein Demo-Push vor dem Paket-Push wäre rot.

### S6b — Abfrage-Editor

**Ziel:** Eine Seite wie der Query Service von Wikidata (ohne die Diagrammarten): ein freies SPARQL-Feld, Tabelle, Karte und Bilder.

**Abnahme:** Jede Standardabfrage läuft wie bisher; Karte und Bilder zeigen, was im Ergebnis steht; zwei Läufe liefern byte-gleiche Seiten.

### Erledigt 2026-10-21 (Code, Tests, Lauf gegen `fuzzy-sl`, Browserprobe mit Pyodide-Attrappe, Abfragen unter echtem Pyodide in Node)

**Gebaut:** `templates/query.html`, in `static/sparql.js` die reinen Funktionen `wktPoint`, `isImageIri`, `imageUrls`, `extractPoints`, `extractImages`, `availableViews`, `parseDefaultView`, `toCsv`, `toSparqlJson`, `errorText`, `tableHtml`, `imagesHtml` und die Seitenlogik (`makeRuntime` für beide Seiten, `initExamples`, `initEditor`); in `sparql.py` `RUNNER_PY` mit `kind`, das Merkmal `image`, eine `#defaultView`-Zeile in `coordinates` und die neue Standardabfrage `images`; in `step_sparql.py` die zweite Seite und der gemeinsame Linkcheck; `base.html` (Navigationslink, `leaflet` lädt Leaflet auch ohne Entitätskarte), `step_build.py` (`ui_query`, `pending` kennt `query.html`), Texte `sq_q_*` und `sq_js_*` in `render.py`, Regeln in `style.css`; Version 0.3.1; `tests/test_sparql.py`; READMEs. Im Demo-Repo: neu gebautes `docs/` (mit `docs/query.html`) und README.

**Befunde:** 28 bis 31 (oben). Dazu:

- 244 Tests laufen durch (226 vorher, 18 neu in `tests/test_sparql.py`): Koordinaten (Länge zuerst, Bereich, andere Himmelskörper), Marker mit Beschriftung und Link, Bilder (Endung, Commons-Vorschau über https), welche Ansichten ein Ergebnis anbietet, `#defaultView`, CSV mit Anführungszeichen, JSON im W3C-Format, `ASK` und `CONSTRUCT` ohne Tabelle, Maskierung von Beschriftung und Bild-URL, Obergrenze von 200 Bildern, Fehlerpositionen ohne Präfixe, das Merkmal `image`, die Editor-Seite mit Beispielen und Navigationslink auf jeder Seite, kein `WARN` im ersten Bau.
- **Die Tests können rot werden:** zehn Mutationen in `sparql.js` (Breite und Länge vertauscht, CSV ohne Anführungszeichen, Endung nicht geprüft, Vorschau über http, Beschriftung nicht maskiert, fremder Himmelskörper angenommen, Karte immer angeboten, Sprache im JSON verloren, `#defaultView` mitten im Text, nicht gebundene Werte im JSON) wurden alle gefangen.
- **Gegen die echten Daten:** alle 13 Abfragen laufen (137, 36, 18, 22, 200, 20, 60, 1, 13, 44, 24, 3, 100 Zeilen), unter CPython und unter echtem Pyodide 0.26.4 mit denselben Zahlen; `ASK`, `CONSTRUCT`, ein doppeltes `PREFIX` und ein Tippfehler laufen dort wie erwartet. `docs/` und `dist/` sind bei zwei Läufen byte-gleich, `--strict` ohne `WARN`.
- **Browserprobe** (Chromium, Pyodide-Attrappe mit vorberechneten Ergebnissen): Auswahl lädt das Beispiel, Strg+Eingabe führt aus, `coordinates` öffnet die Karte mit 60 Markern, Umschalten Tabelle/Karte, CSV mit 61 Zeilen, JSON mit 60 Bindungen, `images` öffnet die Bilder (die Datei selbst lud die Sandbox nicht), `ASK` zeigt „true“ ohne Download-Leiste für Turtle, `CONSTRUCT` zeigt Turtle, Fehlerfall, „Link kopieren“ und Aufruf mit `#q=` füllen das Feld, deutsche Oberfläche samt Beispielnamen, Handybreite ohne waagerechtes Scrollen, „Im Abfrage-Editor öffnen“ von der Beispielseite.
- **Nicht gesehen:** Laden von Pyodide und `micropip` im Browser (Befund 26), Kacheln und Commons-Bilder im Browser, Windows und andere Browser als Chromium, der Lauf von `ci.yml` und `site.yml` auf GitHub.
- **Reihenfolge beim Einspielen:** wie bei S6, erst das Paket pushen, dann im Demo-Repo `pip install --upgrade -r requirements.txt` (0.3.1), `python main.py --strict` und alles committen.

### S7 — CSV-Import und Chublets-Demo

**Ziel:** Aus CSV entsteht Wikibase-JSON in `data/derived/`, das derselbe Renderer verarbeitet; die Chublets-Demo importiert a) das Datenmodell und b) Items aus Wikidata und aus open-archaeo. Dieselbe CSV füllt außerdem die echte Wikibase `chublets-wikibase.de` mit Federation (S7g). Der Schritt ist ein Sammelschritt; gearbeitet wird in S7a bis S7g, je Schritt ein Chat. Die Beschlüsse stehen in A4 (Zeilen „CSV …“, „Kern …“, „RDFS-Brücke“, „Importer …“, „Wikidata-Import“, „open-archaeo-Import“, „Startumfang Chublets“).

```
 Starter Pack            open-archaeo-software.csv        Wikidata (Netz)
 (Modell: Properties,         (data/raw/)                 seeds-wikidata.csv
  Klassen)                         │                           │ import-wikidata
      │ S7b                        │ import-open-archaeo       ▼
      ▼                            ▼                     data/raw/wikidata/ (unverändert)
 ┌──────────────────────── data/csv/ ────────────────────────┐
 │ entities.csv  statements.csv  qualifiers.csv  references.csv │ ◄── apply-qs  data/edits/*.qs (S7e)
 │ idmap.csv     mapping/      seeds-wikidata.csv               │ ◄── von Hand (Calc, GitHub-Editor)
 └───────────────────────────┬────────────────────────────────┘ ◄── to-csv  ◄ data/raw/ (Harvest, S7a)
                             │ from-csv (offline, mit Kern aus dem Paket)
                             ▼
                    data/derived/entities/*.json  →  load → build → search → rdf → sparql
```

```
 data/csv/ ──from-csv──► data/derived/*.json ──► statische Seite (dieses Repo)
                                  │
                                  └──push (S7g, wikibase-federation, wbeditentity)──► chublets-wikibase.de
                                       idmap-<ziel>.csv: CSV-ID → Ziel-ID;  Stubs → wd:Q… aus P4
```

**Das Beispiel (so sieht die Quelle aus):**

```
entities.csv    Q100,class,,,chublet,Chublet,small research software nugget
                Q101,item,,,Alligator,,statistical analysis and ontology tool
                Q102,item,,wikidata-stub,Python,,programming language
                P100,property,string,,source code repository,Quellcode-Repositorium
statements.csv  ,Q100,P1,Q3,,
                ,Q102,P4,Q28865,,wikidata
                ,Q101,P2,Q100,,
                s1,Q101,P100,https://github.com/leiza-rse/alligator,,open-archaeo
references.csv  s1,1,P6,https://open-archaeo.info/post/alligator/
                s1,1,P7,2021-06-04
```

#### S7a — Kern, CSV-Format, `from-csv`, `to-csv`, `csv-fmt`

**Ziel:** Das Paket liest die vier Tabellen und den Kern und schreibt Wikibase-JSON; `to-csv` ist die Umkehrung für Harvest-Daten.

**Uploads:** Standard-Bundle von `wikibase-static`; für die Abnahme ein Klon von `fuzzy-sl-static` (liegt auf GitHub).

Inhalt: `data/kernel/` (Q1 bis Q3, P1 bis P10, A4 „Kern“ und „Kern, Zusatz“); `csv.py` mit dem Wertcodec (A4 „CSV, Wertsyntax“) und dem kanonischen Schreiber; `step_from_csv.py` (statt des Platzhalters), `step_to_csv.py`, `step_csv_fmt.py`; Loader und Wertcodec verstehen föderierte Werte und Properties (`wd:Q…` und `wd:P…` in der CSV; im Wikibase-JSON die Entity-URI `http://www.wikidata.org/entity/Q…` als `id` bzw. als Property-Schlüssel, Form wie in `wikibase-federation`), sie werden nur verlinkt (A4 „Föderierte Properties und Werte“, vorher nur im Renderer, jetzt auch im Loader und Validator ohne `WARN`); Spalte `origin` in `entities.csv`; Validator mit den `WARN`-Regeln aus A4 „Kern, Validierung“, jede mit `datei:zeile`; Eintrag im Orchestrator: `from-csv` steht im Standardlauf vor `load`, denn `load` liest `data/derived/` (Reihenfolge `from-csv`, `load`, `build`, …). `from-csv` löscht veraltete Dateien in `data/derived/entities/`, die keine CSV-Zeile mehr haben. Version 0.4.0 (Befund 21).

**Abnahme:** (1) Rundlauf: `to-csv` auf `data/raw/` von `fuzzy-sl-static`, danach `from-csv` in ein leeres `data/derived/`; `load` meldet dieselben 173 Entitäten (137 Items, 36 Properties), 488 Statements und 41 Belege wie für `data/raw/`, und ein Vergleich der Entitäten nach Normalisierung (Schlüssel sortiert, `hash`, `id`, `lastrevid`, `modified` ausgenommen) findet keinen Unterschied. (2) Zwei Läufe hintereinander, `git status --porcelain` leer; `csv-fmt` auf einer kanonischen Datei ändert nichts. (3) Jede `WARN`-Regel hat einen Test mit einer absichtlich fehlerhaften Zeile (Kern verändert, Klasse ohne Weg nach Q3, Item ohne Klasse, Wert gegen Datentyp, Zeitformat, Doppelte ID, unbekannte Property). (4) Bestehende 244 Tests bleiben grün.

#### S7b — Modell und Demo-Repo

**Ziel:** `chublets-wikibase-demo` baut eine Seite, die nur das Modell des Starter Packs zeigt, und die RDFS-Brücke ist im Export.

**Uploads:** Starter Pack, Bundle des Pakets (nach S7a); das Demo-Repo legt Florian vorher leer an.

Inhalt: Gerüst des Demo-Repos (`main.py`-Wrapper, `requirements.txt`, `site.yaml` mit `rdf_base`, `pages_url`, `formatter_property: P5`, `.github/workflows/site.yml` als Aufrufer, `README.md`, `.gitignore`, `.gitattributes`); `data/csv/entities.csv` mit den 153 Properties aus `wikibase-property-set.csv` (`wb_label` → `label_en`, `datatype` → `datatype`, `wikidata_pid` → P4-Aussage mit Beleg; `status`, `phase`, `confidence` und `codemeta_terms` als Aussagen nur, wenn das Modell dafür Properties vorsieht, sonst in `docs/` des Demo-Repos als Hintergrund); Klassen aus `wikidata-entities.csv` und `bootstrap-order` Schritt 5 (chublet, Little Minion, research software, software library, application software, script file) mit Weg nach Q3 und P4-Zwillingen; Importskript `tools/import_pack.py` im Demo-Repo (einmalig, Ergebnis ist die CSV). RDFS-Brücke in `rdf.py` (A4). Entscheiden vor dem Bau: Kann P4 an Properties mehr als ein Ziel haben (Crosswalk 1:n)? Standard ist „ja, mehrere Aussagen“.

**Abnahme:** Das Demo baut offline mit `python main.py --strict`; 0 `WARN`; Kern vollständig; die Seite zeigt Q1 bis Q3 und P1 bis P10 mit ihren Aussagen; die Standardabfragen des Pakets laufen (keine leere außer den mit `requires:` ausgelassenen); `rdf` enthält die Brückentripel nur mit Kern, der Test dazu ist rot, wenn man den Kern entfernt; zwei Läufe, `git status` sauber.

#### S7c — open-archaeo-Importer

**Ziel:** Ein Ausschnitt von etwa 100 Software-Einträgen steht als Items mit Belegen in der CSV.

**Uploads:** Bundle beider Repos; `open-archaeo-software.csv` und `data/open-archaeo-columns.csv` aus dem Pack.

Inhalt: `step_import_open_archaeo.py` mit Zuordnungstabelle (A4 „open-archaeo-Import“), `idmap.csv`, Tags und Autoren als Items. Die Entscheidungen des Packs (Identity-Block in drei Varianten, Teil D) werden hier gefällt, bevor der Importer läuft.

**Abnahme:** Das Demo baut offline mit dem Ausschnitt; Seiten, Suche und SPARQL funktionieren wie bei der gesicherten Wikibase; der Bericht nennt die Zahl der Entitäten und Tripel (das ist die Messung für den vollen Bestand, Teil D); ein Reimport ändert nichts (`git status` sauber); ein von Hand geänderter und von `origin` befreiter Wert überlebt den Reimport.

#### S7d — Wikidata-Importer

**Ziel:** Items und Klassen aus Wikidata stehen mit lokalen IDs und Zwilling in der CSV.

**Uploads:** Bundle beider Repos; Fixtures mit echten Wikidata-Antworten von Florian (`Special:EntityData/Q74003194.json` o. ä.), weil die Sandbox Wikidata nicht erreicht (Befund 35).

Inhalt: `step_import_wikidata.py` (A4 „Wikidata-Import“), Fixture-Tests, Lückenbericht. Abgleich mit open-archaeo über die Repository-URL (`sparql/02-reconcile-by-repository.rq`) nur als Bericht, Zusammenführen später (Teil D).

**Abnahme:** Mit den Fixtures: kein Item-Wert mit fremder ID (Test über alle Werte), Lückenbericht nennt Zahl und Liste der nicht zugeordneten Properties, zweiter Lauf schreibt nichts (Revisionsvergleich), „retrieved“ stammt aus den Daten. Bei Florian: ein echter Lauf mit drei Seeds, danach `python main.py --strict` und beide Läufe sauber.

#### S7e — Update-Kanal `apply-qs`

**Ziel:** Eine `.qs`-Datei ändert die CSV, ohne dass jemand eine Tabelle von Hand anfasst.

**Uploads:** Bundle; die QuickStatements-Hilfe als Text oder Link (Befund 37).

Inhalt: Parser für die Teilmenge (A4 „CSV, Update-Kanal“), Wertcodec in beide Richtungen, `data/edits/applied.csv`, Meldung aller nicht unterstützten Befehle als `WARN` mit Zeile.

**Abnahme:** `alligator.qs` aus dem Pack (auf lokale IDs umgeschrieben) erzeugt die erwarteten Zeilen; dieselbe Datei ein zweites Mal wirkt nicht; `-`-Zeilen entfernen genau eine Aussage; ungültige Zeilen verändern nichts (alles oder nichts je Datei); die kanonische Form bleibt erhalten.

#### S7f — Reiter „Source rows“

**Ziel:** Jede Entitätsseite zeigt, in welchen CSV-Zeilen sie steht.

Inhalt: Reiter neben „Original“ (nur bei CSV-Daten), Block mit den Zeilen der vier Tabellen als Text (Kopieren-Schaltfläche), Link auf die Datei im GitHub-Editor (`site.yaml`: `edit_url`, optional). Die Seite bleibt read-only; es gibt keinen Schreibzugriff aus dem Browser (kein Token, kein Backend).

**Abnahme:** Linkcheck grün; der Block einer Seite stimmt zeichengenau mit den Zeilen der CSV überein (Test); ohne CSV-Daten kein Reiter, die Seiten der Harvest-Demos bleiben byte-gleich.

#### S7g — Push in die echte Wikibase

**Ziel:** `chublets-wikibase.de` bekommt Kern, Modell und Items aus derselben CSV wie die statische Seite.

**Uploads:** Bundle von `wikibase-federation` (ohne `config.ini`), `data/derived/` des Demo-Repos (oder dessen Bundle), ein Bot-Zugang nur bei Florian lokal; Angabe, ob `url` auf dem Ziel erlaubt ist und ob Federation eingeschaltet ist.

Inhalt (alles im Repo `wikibase-federation`, Usecase `usecases/chublets/`): `pipeline.py` im Muster des Software-Usecases (A4 „Push-Weg“, „Ziel-Wikibase, IDs“, „Wikidata-Werte beim Push“, „Properties beim Push“): (1) Kern anlegen und IDs prüfen, (2) Properties mit Datentyp, (3) Items mit Labels, Descriptions, Aliases, (4) Aussagen mit Qualifiern und Belegen über `wbeditentity`, IDs über `idmap-<ziel>.csv`; Schalter `values`, `url_as_string`; Trockenlauf als Standard mit Liste der Aufrufe; Bericht mit Zahl angelegter, übersprungener und fehlgeschlagener Entitäten und Aussagen. Die Tests laufen gegen eine Attrappe der API; echte Antworten von `chublets-wikibase.de` (`siteinfo`, ein `wbgetentities`) bringt Florian als Fixture mit.

**Abnahme:** Trockenlauf mit Kern und drei Items: die Liste der Aufrufe stimmt mit dem Erwarteten (Test); `wd:`-Wert statt Stub; keine fremde ID in einem lokalen Wert; zweiter Trockenlauf nach einem echten Lauf meldet 0 Schreibaufrufe. Bei Florian: echter Lauf auf der leeren Wikibase; Q1 bis Q3 und P1 bis P10 haben die IDs der CSV (sonst Abbruch, wie vorgesehen); ein Item mit Qualifier, Beleg und föderiertem Wert erscheint in der Oberfläche; ein zweiter Lauf schreibt nichts.

### S8 — Pages-Workflow und CI

**Ziel:** Ein Push baut `docs/` und prüft Determinismus und Linkcheck mit `python main.py --strict`.

**Abnahme:** Der Workflow läuft grün; ein absichtlich toter Link lässt ihn rot werden. Ergänzt 2026-10-21: Beides gilt zuerst lokal (`tests/test_ci.py`) und dann auf GitHub, jeweils im Paket-Repo (`ci.yml`) und in einem Site-Repo (`site.yml` über den Aufrufer); die Probe mit totem Link läuft in einem Zweig, der nicht gemergt wird.

### Erledigt 2026-10-21 (Code, Tests, Probe lokal; Lauf auf GitHub offen)

**Gebaut:** `.github/workflows/ci.yml` (Tests und Pipeline zweimal), `.github/workflows/site.yml` (wiederverwendbar: `check` und `deploy`), `examples/site-caller.yml`, `tests/test_ci.py`; im README der Abschnitt „Continuous integration“ und das Layout. Am Code von `main.py` und den Schritten ändert sich nichts: Der Linkcheck war seit S3 ein `WARN` des Schritts `build`, `--strict` seit S1 die Umwandlung in Exit 1. S8 verdrahtet beides in CI und belegt es.

**Befunde:**

- 14 neue Tests, zusammen 101 (24 Loader, 10 Harvest, 48 Build, 5 Main, 14 CI). Sie führen aus, was der Workflow ausführt, gegen ein temporäres Site-Repo aus den Fixtures: sauberer Strict-Lauf (`0 dead`, kein `WARN`); handgeschriebene `docs/impressum.html` mit Link auf eine fehlende Datei gibt Exit 1 und die Zeile `WARN: [build] dead internal link impressum.html -> datenschutz.html`; ohne `--strict` nur Warnung (Exit 0); mit vorhandenem Ziel wieder grün (Befund 14). In einem echten Git-Repo: Lauf, Commit, danach zwei Läufe mit `PYTHONHASHSEED=2` und `=3` und leeres `git status --porcelain`; eine eingecheckte, von Hand veränderte Seite und eine fehlende Seite werden als Abweichung erkannt (Befund 15).
- **Die Tests können rot werden** (zwei Mutationen, danach zurückgenommen, `git status` wieder wie vorher): Mit abgeschaltetem Linkcheck schlagen die beiden Tests zum toten Link fehl; mit einer vom Hash-Seed abhängigen Zeile in `docs/index.html` schlägt der Zwei-Läufe-Test fehl (` M docs/index.html`).
- `actionlint` 1.7.12 meldet an `ci.yml`, `site.yml` und `examples/site-caller.yml` nichts. Der Job `pipeline` im Paket-Repo, lokal nachgestellt (`python main.py --strict` zweimal, `git status --porcelain`): beide Läufe Exit 0, Baum sauber, der eingecheckte `dist/pipeline_report.txt` bleibt unverändert.
- Gesamtlauf `python -m unittest discover -s tests`: 101 Tests, OK, etwa 19 Sekunden.

**Erster Lauf auf GitHub** (2026-10-21, Commit `60f96d3`, nach dem Push durch Florian): drei von vier Jobs grün, nämlich Tests auf Ubuntu mit Python 3.10 und 3.13 sowie der Job `pipeline` (strict, zweimal, Baum sauber), zusammen 39 Sekunden. Rot war nur `tests (windows-latest, Python 3.13)` mit einem Fehler in 101 Tests, die Ursache steht in Befund 16 (Fixture, nicht Produktionscode). Alle 101 Tests laufen also unter Python 3.10 durch, passend zu `requires-python >=3.10`. Außerdem steht in den drei Ubuntu-Jobs je ein Hinweis, dass das Label `ubuntu-latest` ab dem 19. Oktober 2026 auf Ubuntu 26 zeigt (Teil D).

**Zweiter Lauf auf GitHub** (2026-10-21, Commit `e759577`, „Resolve the temporary root in the build test fixture“): alle vier Jobs grün, 59 Sekunden, darunter `tests (windows-latest, Python 3.13)`. Damit sind Ubuntu mit 3.10 und 3.13, Windows mit 3.13 und die Zwei-Läufe-Prüfung des Paket-Repos belegt.

**Demo-Repo `fuzzy-sl-static`** (2026-10-21, nach dem Einspielen des Patches): Der Wrapper brauchte `--strict` und `load` (Befund 17). Lauf `Site` #2 auf `main` (Commit `f2127fc`): `check` 14 s, `deploy` 12 s, zusammen 33 s, grün; Artefakt `github-pages` 436 KB; die Seite ist unter `https://n4o-rse.github.io/fuzzy-sl-static/` erreichbar, Pages-Quelle „GitHub Actions“. Abgerufen und gelesen (Startseite und `Q97`): 173 Entitäten, Logo, EN/DE, Boxen je Property, Fußzeile mit Quelle, Stand und CC0 1.0.

**Probelauf mit totem Link** (Pull Request #1, `probe-dead-link`, Commit `00e8245`, `docs/impressum.html` mit Link auf `datenschutz.html`): `Site / check (strict, run twice, tree clean)` schlägt nach 11 s fehl, `Site / deploy to GitHub Pages` wird übersprungen (Screenshot von Florian). Die Zeile `WARN: [build] dead internal link …` im Log wurde nicht eingesehen; sie ist lokal belegt (`tests/test_ci.py`, Lauf an den Echtdaten). Der grüne Merge-Button blieb trotz rotem Check sichtbar, weil im Repo keine Branch-Schutzregel den Check verlangt. Das Schließen des Pull Requests ohne Merge und das Löschen des Zweigs sind Aufräumarbeit. **Abnahme von S8 damit erfüllt.**

**Nicht geprüft:** `deploy` und `environment` (brauchen die Pages-Quelle „GitHub Actions“); der Aufruf aus dem Demo-Repo auf GitHub (lokal mit den echten Daten geprüft, Befund 17); der rote Probelauf mit totem Link auf GitHub.

### S9 — Template-Repo

**Ziel:** `wikibase-static-template` lässt sich als GitHub-Template nutzen: `site.yaml`, Workflow, installiert das Paket per pip.

**Abnahme:** Ein neues Repo aus dem Template baut und veröffentlicht eine Seite ohne weiteren Code.

### S10 — Skill

**Ziel:** Ein Skill, der Konventionen und Zwischenformat aus dem Repo beschreibt (mit `skill-creator`).

**Abnahme:** Der Skill erzeugt aus einer Beispiel-Wikibase eine Seite nach den Regeln aus A3.

---

## Teil D — Offene Punkte

- **Anubis und die API:** `api.php` von `fuzzy-sl` ist für den Harvest erreichbar (Befund 7); `Special:EntityData` wurde nicht geprüft und wird nicht gebraucht. `--from-dir` bleibt der Fallback für Wikibases, die `api.php` schützen.
- **Demo-Repo `fuzzy-sl-static`:** enthält `data/raw/`, ab S3 auch `site.yaml` und `docs/` (`python main.py build`). Der Harvest läuft mit `WBS_ROOT` im Demo-Repo, damit `data/raw/` des Paket-Repos leer bleibt. GitHub Pages ist noch nicht eingerichtet; der Workflow dafür steht mit S8 bereit (`examples/site-caller.yml`, Quelle „GitHub Actions“, A4), eingelegt ist er dort noch nicht.
- **Node.js 20 in den Pages-Actions:** Der Lauf im Demo-Repo meldet, dass `actions/configure-pages@v5`, `actions/deploy-pages@v4` und die Upload-Action (aus `upload-pages-artifact@v4`) Node.js 20 anfordern und auf Node 24 gezwungen werden. Unkritisch, solange der Lauf grün ist; offen ist, ob es neuere Hauptversionen gibt, die man einsetzt (nachsehen vor dem nächsten Eingriff in `site.yml`, dann Zeile „Versionen der Actions“ in A4 anpassen).
- **S6, Browserprobe bei dir:** Auf der Live-Seite `…/sparql.html` auf „Ausführen“ klicken: Pyodide kommt von `cdn.jsdelivr.net`, rdflib per `micropip` von PyPI (Befund 26, in der Sandbox nicht möglich). Erwartet: Status „Ready: 12456 triples.“, danach Tabellen mit den Zeilenzahlen aus Befund 26; die Abfrage `references` braucht am längsten.
- **S6b, Browserprobe bei dir:** Auf der Live-Seite `…/query.html` das Beispiel „Items with coordinates“ laden und mit Strg+Eingabe ausführen: erwartet die Karte mit 60 Markern (Kacheln von OSM), dann „Items with an image“: ein Bild von `upload.wikimedia.org`. Außerdem `ASK { wd:Q42 ?p ?o }`. Wie bei S6 geht das nur im Browser (Befund 26).
- **S6b, Diagramme:** Die Ansichten des Query Service von Wikidata außer Tabelle, Karte und Bildern (Balken, Zeitleiste, Graph, Bubble) gibt es nicht; `#defaultView` mit anderen Namen wird ignoriert. Erst bei Bedarf; Balken und Zeitleiste ließen sich aus der Tabelle bauen, ohne etwas nachzuladen.
- **S6b, Teilen:** Der Link trägt die Abfrage in der Adresse; Ergebnisse stehen nicht darin, und der Aufruf führt nichts aus (sonst würde er Pyodide laden, bevor jemand klickt). Ein `#q=…&run` wäre möglich, wenn das gewünscht ist.
- **S6, DCAT und Ontologie (Vorschlag zur Bestätigung):** Catalog = Wikibase mit zwei Unterkatalogen, Dataset = Entität, Distributions = JSON, Turtle, HTML (A4 „RDF, DCAT 3“). Offen: ob es zusätzlich `foaf:primaryTopic` statt oder neben `dcterms:subject` sein soll, ob ein DCAT-AP-Profil (Pflichtfelder wie `dcterms:publisher`, `dcat:contactPoint`) gewünscht ist (dafür bräuchte `site.yaml` Felder), ob die IRIs unter `<base>/catalog/…` bleiben oder unter einem w3id-Präfix liegen (siehe unten), und ob die Ontologie um die vier fehlenden Begriffe ergänzt wird (Befund 23).
- **S6, `wdtn:`, Sitelinks, Dump-Metadaten** fehlen im Export (A4 „RDF, Abweichungen“); erst bei Bedarf, etwa wenn eine Abfrage für den Query Service `wdtn:` nutzt.
- **S6, Statuszeile der Query-Seite** bleibt nach dem Umschalten der Sprache in der Sprache stehen, in der sie gesetzt wurde (die Tabelle und die Felder wechseln). Kleinigkeit; behoben wird sie, wenn jemand sie vermisst.
- **S6, Laufzeit großer Exporte:** gemessen nur bei 12 456 Tripeln (Parsen eine Sekunde, längste Abfrage 5,7 Sekunden unter Pyodide in Node). Bei einigen zehntausend Entitäten ist ein Browser-Parsen der Gesamtdatei nicht mehr bequem; dann braucht es eine Auswahl oder einen Endpoint.
- **Ein Push auf einen Zweig löst `site.yml` nicht aus**, nur `main` und Pull Requests (der Aufrufer hat `on: push: branches: [main]` und `pull_request`). Für Proben gilt deshalb: Zweig pushen und einen Pull Request öffnen (Befund aus dem Probelauf 2026-10-21).
- **`ubuntu-latest` wird Ubuntu 26:** GitHub meldet in jedem Job, dass das Label ab dem 19. Oktober 2026 auf Ubuntu 26 zeigt (`actions/runner-images`, Issue 14748). Die Läufe waren grün. Entscheidung offen: das Label behalten und Brüche in Kauf nehmen, oder auf `ubuntu-24.04` festlegen, bis es nötig ist; beim Festlegen entfällt die Meldung. Eine feste Version macht die Läufe über die Zeit gleich, kostet aber irgendwann eine Umstellung.
- **Schreibzugriff der Claude-GitHub-App:** Pushes aus Chats werden für `n4o-rse/wikibase-static` abgelehnt; bis die App für die Organisation installiert ist, kommt jede Änderung als Patch-ZIP.
- **Sichtprobe von S3 bei dir:** Eine Seite mit Karte (Kacheln) und einem Commons-Bild im eigenen Browser ansehen. In `fuzzy-sl` gibt es kein Bild; die Probe geht mit der Chublets-Demo (S7) oder einer Fixture mit echtem Dateinamen. Seit 2026-10-21 geht das an der Live-Seite `https://n4o-rse.github.io/fuzzy-sl-static/` (`Q97`, `Q74`); die Karte wird per JavaScript gezeichnet und ließ sich beim Abruf nicht prüfen.
- **Kartenkacheln:** Die Seiten laden Kacheln von `tile.openstreetmap.org`. Für Demos ist das üblich, für viel Verkehr verlangt die Nutzungsrichtlinie von OSM einen anderen Anbieter; dann wäre ein Schlüssel in `site.yaml` nötig.
- **Suche, mögliche Folgen:** eine Ergebnisseite oder `search.html` für „alle Treffer“ (die Liste zeigt höchstens zehn), Enter öffnet heute den ersten Treffer, Suche in Beschreibungen und nachsichtiger Abgleich bei Tippfehlern; erst bei Bedarf, denn bei dreistelliger Größe reicht das Vorhandene. Ob der Index bei einigen tausend Entitäten noch bequem lädt, ist nicht gemessen (heute 27 300 Byte für 173).
- **Node.js in CI:** Die Tests des Abgleichs brauchen `node`. Die GitHub-Runner haben es, das wurde aber nicht geprüft; wo es fehlt, werden die Tests übersprungen und der Lauf bleibt grün. Beim ersten Lauf auf GitHub prüfen, dass alle 244 Tests laufen und keiner übersprungen wird (die Node-Tests von Suche und Query-Seite); falls doch, in `ci.yml` einen Schritt `actions/setup-node` ergänzen.
- **Browserprobe der Suche bei dir:** Feld, Treffer und Umschalten in einem Browser außer Chromium und unter Windows ansehen, am besten auf der Live-Seite nach dem Neubau.
- **Wikibase-Look, Feinheiten:** Die Sprachkennzeichen („Englisch“ klein hinter Label und Beschreibung) fehlen noch, ebenso eine Möglichkeit, eigene Farben außer dem Akzent zu setzen. Das CSS ist eine Annäherung, kein Pixel-Nachbau; Wünsche kommen als Screenshot mit Markierung.
- **Lizenz der gesicherten Daten:** Entschieden ist CC0 als Standard (A4, 2026-10-20). Offen bleibt nur die Gegenprobe: Die Hosting-Seiten von wikibase.cloud ließen sich in der Sandbox nicht lesen (die Seite braucht JavaScript, der MediaWiki-Entwurf lieferte 404), und ein Erfahrungsbericht zu wikibase.cloud rät, eigene Nutzungsbedingungen anzugeben, statt von CC0 auszugehen. Für `fuzzy-sl` also beim Betreiber bestätigen; hat eine Wikibase eine andere Lizenz, steht sie als `license` in `site.yaml`.
- **Mehrere Wikibases in einer Seite:** vorerst nicht vorgesehen.
- **S7, Identity-Block** des Packs liegt in drei Varianten vor (`MAPPING.md`, `model.py`, WikiProject-Seite; `data/identity-block-variants.csv`): vor S7c festlegen, welche Aussagen jedes Software-Item mindestens trägt; als Formular im S7c-Chat.
- **S7, Pack-Lücken:** 12 Registry-ID-Properties und 8 Distro-Paket-Labels fehlen (`tools/check_completeness.py` mit dem WikiProject-Text), alle Q-IDs und Labels „recalled“ sind unverifiziert (`tools/verify_wikidata.py` bei Florian). Wirkt auf S7b (Modell) und S7d (Zwillinge); bis dahin trägt das Modell die Zuverlässigkeit des Packs.
- **S7, Größe des vollen Bestands:** Gemessen ist nur `fuzzy-sl` (12 456 Tripel, Abfragen längstens 5,7 Sekunden unter Pyodide in Node). 416 Software-Einträge mit Autoren und Tags ergeben vermutlich ein Mehrfaches; geschätzt, nicht gemessen. S7c liefert die Messung am Ausschnitt; erst danach entscheidet sich, ob der volle Bestand in den Browser passt (Teil D „Laufzeit großer Exporte“).
- **S7, Zusammenführen von Wikidata und open-archaeo:** Software, die in beiden vorkommt, soll ein Item sein (Abgleich über die Repository-URL, P1324). Vorerst nur Bericht (S7d); das Zusammenführen und die Frage, welche Quelle bei Widerspruch gewinnt, sind offen.
- **S7, Gleiches Muster für `wikibase-federation`:** Der Kern (P1 bis P10) und das Starter Pack könnten dort in den frozen Usecase zurückfließen oder ihn ablösen; Entscheidung von Florian, nicht Teil von S7.
- **S7, echte Wikibase aus der CSV:** `export-qs` (CSV → QuickStatements mit Zuordnung lokale ID → neue ID) würde die Chublets-Wikibase auf Wikibase Cloud füllen; nicht in S7, aber das Format (Wertcodec, Update-Kanal) ist dafür gebaut.
- **S7, Ontologie-Ergänzung:** Die Wikibase-Systemontologie kennt die vier Begriffe nicht, die der Dump benutzt (Befund 23); zusammen mit den Brückentripeln (A4 „RDFS-Brücke“) ein Anlass, über eine eigene Ergänzungsdatei neben der Originalontologie zu entscheiden.
- **S7g, Gleiche IDs in Demo und echter Wikibase:** Nur der Kern bekommt auf einer leeren Wikibase dieselben IDs. Domänen-IDs ab 100 kann die Wikibase nicht verteilen; die statische Demo und `chublets-wikibase.de` zeigen also verschiedene Nummern für dasselbe Item. Mögliche Auswege (nicht entschieden): Füllentitäten bis 99 anlegen, nach dem ersten Push die Ziel-IDs in die CSV zurückschreiben (verletzt „IDs bleiben“ nicht, wenn es vor der ersten Veröffentlichung der Demo geschieht), oder die Demo anzeigen lassen, was `idmap` sagt.
- **S7g, Ziel ungeprüft:** Version, Federation-Schalter, Datentyp `url` und Berechtigungen von `chublets-wikibase.de` sind ungeprüft (Befund 39); der erste Trockenlauf mit `siteinfo` klärt das.
- **S7g, `wbeditentity` nicht erprobt:** Dass die Zwischenfürm ohne Umbau angenommen wird (Befund 39), ist eine Folgerung; die Probe mit Fixtures und dann bei Florian steht aus. Föderierte Werte sind laut README von `wikibase-federation` noch alpha.
- **w3id-Präfix** für die Dummy-Wikibase und Content Negotiation: offen, erst relevant ab S9; die DCAT-IRIs (A6) wären dort ebenfalls zu verankern.
