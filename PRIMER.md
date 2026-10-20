# PRIMER — wikibase-static

Arbeitsplan für `n4o-rse/wikibase-static`. Wird zu Beginn jedes Chats hochgeladen (Bundle, siehe A5) und am Ende zurückgeschrieben. Stand: 2026-10-20 (nach S3).

Sprache: dieses Dokument ist deutsch, alles andere im Repo (Code, Kommentare, README) ist britisches Englisch.

---

## Teil A — Immer gültig

### A1 Ausgangslage

**Ziel in einem Satz:** Eine bestehende Wikibase (z. B. Wikibase Cloud) per API sichern oder eine Dummy-Wikibase aus CSV aufbauen und beides als statische, read-only Seite auf GitHub Pages veröffentlichen, die wie eine Wikibase aussieht und sich so bedienen lässt (Q-/P-IDs anklicken, externe Links im neuen Tab), mit Suche, Karte und SPARQL-Seite im Browser.

| Repo | Rolle | Status |
|---|---|---|
| `n4o-rse/wikibase-static` | Paket, Orchestrator `main.py`, alle Schritte (dieses Repo) | neu, S1 |
| `n4o-rse/wikibase-static-template` | GitHub-Template-Repo: `site.yaml`, Pages-Workflow, installiert `wikibase-static` per pip | geplant, S9 |
| `n4o-rse/fuzzy-sl-static` | Demo 1: Rettung von `fuzzy-sl.wikibase.cloud` | angelegt 2026-10-20: `data/raw/` gefüllt (S4), dünnes Gerüst mit `main.py`-Wrapper; mit S3 kommen `site.yaml` und `docs/` (`python main.py build`); Workflow mit S8/S9 |
| `n4o-rse/chublets-wikibase-demo` | Demo 2: Dummy-Wikibase aus CSV (Ideen von chublets.software, `open-archaeo/py`) | geplant, S7 |

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
2. **Read-only und statisch:** Die veröffentlichten Seiten senden keine Anfragen an die Quell-Wikibase. Erlaubt sind nur Commons-Bilder, Kartenkacheln und Links, die der Nutzer anklickt.
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
- **Netzwerk nur im Schritt `harvest`.** Alles andere läuft offline gegen die Daten auf der Platte. `harvest` ist nie Teil des Standardlaufs, sondern hat ein eigenes Verb: `python main.py harvest`.
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
| Suche | Autocomplete wie Wikidata (Label, Beschreibung, ID), im Browser | 2026-10-20 |
| Suche, Technik | JSON-Index mit MiniSearch | Vorschlag |
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
| Datei- und Seitenaufbau | Je Entität `docs/<ID>.html`, dazu `docs/index.html` (Titel, Beschreibung, Zählung, Tabellen der Items und Properties) und `docs/assets/` (`style.css`, `app.js`, `map.js`, `vendor/leaflet/`, optional `logo/`). Die Quelltexte liegen im Paket (`templates/`, `static/`, in `pyproject.toml` als Paketdaten eingetragen) und werden beim Bauen nach `docs/assets/` kopiert | Vorschlag |
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

### A5 Was in welchem Chat hochgeladen wird

Ein Bundle statt Einzeldateien. Mitnehmen: `PRIMER.md`, Quelltexte, kleine Daten. Nicht mitnehmen: `.git/`, `.venv/`, `config.local.*`, große erzeugte Dateien.

```cmd
robocopy . ..\wikibase-static-bundle /E /XD .git .venv __pycache__ build /XF config.local.ini config.local.json >nul & powershell -NoProfile -Command "Compress-Archive -Path ..\wikibase-static-bundle\* -DestinationPath ..\wikibase-static-bundle.zip -Force"
```

(robocopy meldet Erfolg mit Exit-Code unter 8, das ist normal.) Für S4 zusätzlich ein paar im Browser gesicherte JSON-Dateien aus `fuzzy-sl`, falls Anubis den Abruf blockiert.

### A6 IRI-Landkarte

Das Repo veröffentlicht RDF (S6). Vorschlag: Die RDF-Dateien verwenden die Konzept-URIs der Quell-Wikibase (z. B. `https://fuzzy-sl.wikibase.cloud/entity/Q1`), damit dieselben Queries wie gegen die echte Wikibase laufen. Bei der Dummy-Wikibase kommt die Basis aus `site.yaml`.

| Pfad | Inhalt | Ziel des Redirects | Status |
|---|---|---|---|
| `dist/<site>.ttl` | RDF aller Entitäten im Wikibase-Modell | – (Datei auf Pages) | geplant |
| `docs/sparql.html` | Query-Seite im Browser | – | geplant |
| w3id-Präfix für die Dummy-Wikibase | offen | offen | geplant |

---

## Teil B — Schrittübersicht

| ID | Schritt | Repo | hängt ab von | Status |
|---|---|---|---|---|
| S0 | Festlegungen: Zwischenformat, `site.yaml`-Schema, Seiten-URLs | wikibase-static | – | erledigt 2026-10-20 |
| S1 | Skeleton: Layout, `main.py`, `utils.py`, Lizenz, Citation | wikibase-static | – | erledigt 2026-10-20 |
| S2 | Loader und Validator für das Zwischenformat, Label-Auflösung | wikibase-static | S0, S1 | erledigt 2026-10-20 |
| S3 | Renderer: Item- und Property-Seiten im Wikibase-Look, Leaflet, Commons, Linkcheck | wikibase-static, fuzzy-sl-static | S2 | erledigt 2026-10-20 (Sichtprobe mit Commons-Bild und Kacheln bei dir offen, Teil D) |
| S4 | Harvest, inkrementell, `--probe`, `--from-dir`; Test mit `fuzzy-sl` | wikibase-static, fuzzy-sl-static | S0, S1 | erledigt 2026-10-20 |
| S5 | Suche mit Autocomplete | wikibase-static | S2 | offen |
| S6 | RDF-Export und SPARQL-Seite | wikibase-static | S2 | offen |
| S7 | CSV-Import und Chublets-Demo | wikibase-static, chublets-wikibase-demo | S2 | offen |
| S8 | Pages-Workflow, Determinismus- und Linkcheck in CI | wikibase-static | S3 | offen |
| S9 | Template-Repo `wikibase-static-template` | wikibase-static-template | S3, S8 | offen |
| S10 | Skill aus dem bewährten Repo | – | S9 | offen |

S0 und S1 sind unabhängig voneinander. Nach S2 sind S3, S5, S6 und S7 voneinander unabhängig und können in beliebiger Reihenfolge laufen; S4 braucht nur das Zwischenformat aus S0 und kann schon vor S2 beginnen, weil `data/raw/` nur Rohdaten ablegt. S8 braucht mindestens S3. Ein Chat darf auf S4 starten, auch wenn S2 noch offen ist.

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

### S6 — RDF und SPARQL

**Ziel:** `dist/<site>.ttl` im Wikibase-RDF-Modell und `docs/sparql.html` mit Beispielqueries.

**Abnahme:** Jede Beispielquery liefert in der Prüfung mindestens eine Zeile; Turtle ist byte-identisch bei zwei Läufen (sortierte N-Triples als Zwischenschritt).

### S7 — CSV-Import und Chublets-Demo

**Ziel:** Aus CSV und einer Mapping-Datei entsteht Wikibase-JSON in `data/derived/`, das derselbe Renderer verarbeitet.

**Uploads:** `open-archaeo/py` und die relevanten CSV-Dateien.

**Abnahme:** Die Demo baut ohne Netzwerk; Seiten, Suche und SPARQL funktionieren wie bei der gesicherten Wikibase.

### S8 — Pages-Workflow und CI

**Ziel:** Ein Push baut `docs/` und prüft Determinismus und Linkcheck mit `python main.py --strict`.

**Abnahme:** Der Workflow läuft grün; ein absichtlich toter Link lässt ihn rot werden.

### S9 — Template-Repo

**Ziel:** `wikibase-static-template` lässt sich als GitHub-Template nutzen: `site.yaml`, Workflow, installiert das Paket per pip.

**Abnahme:** Ein neues Repo aus dem Template baut und veröffentlicht eine Seite ohne weiteren Code.

### S10 — Skill

**Ziel:** Ein Skill, der Konventionen und Zwischenformat aus dem Repo beschreibt (mit `skill-creator`).

**Abnahme:** Der Skill erzeugt aus einer Beispiel-Wikibase eine Seite nach den Regeln aus A3.

---

## Teil D — Offene Punkte

- **Anubis und die API:** `api.php` von `fuzzy-sl` ist für den Harvest erreichbar (Befund 7); `Special:EntityData` wurde nicht geprüft und wird nicht gebraucht. `--from-dir` bleibt der Fallback für Wikibases, die `api.php` schützen.
- **Demo-Repo `fuzzy-sl-static`:** enthält `data/raw/`, ab S3 auch `site.yaml` und `docs/` (`python main.py build`). Der Harvest läuft mit `WBS_ROOT` im Demo-Repo, damit `data/raw/` des Paket-Repos leer bleibt. GitHub Pages ist noch nicht eingerichtet (Branch `main`, Ordner `/docs`); der Workflow kommt mit S8/S9.
- **Sichtprobe von S3 bei dir:** Eine Seite mit Karte (Kacheln) und einem Commons-Bild im eigenen Browser ansehen. In `fuzzy-sl` gibt es kein Bild; die Probe geht mit der Chublets-Demo (S7) oder einer Fixture mit echtem Dateinamen.
- **Kartenkacheln:** Die Seiten laden Kacheln von `tile.openstreetmap.org`. Für Demos ist das üblich, für viel Verkehr verlangt die Nutzungsrichtlinie von OSM einen anderen Anbieter; dann wäre ein Schlüssel in `site.yaml` nötig.
- **Suchfeld im Kopf:** fehlt bis S5; die Kopfzeile hat dafür noch keinen Platz reserviert.
- **Wikibase-Look:** Das CSS ist ein ruhiger Entwurf in Anlehnung an Wikibase, kein Pixel-Nachbau; Anpassungen (Farben, Schrift) gehen über `colour` und das CSS im Paket.
- **Lizenz der gesicherten Daten:** Entschieden ist CC0 als Standard (A4, 2026-10-20). Offen bleibt nur die Gegenprobe: Die Hosting-Seiten von wikibase.cloud ließen sich in der Sandbox nicht lesen (die Seite braucht JavaScript, der MediaWiki-Entwurf lieferte 404), und ein Erfahrungsbericht zu wikibase.cloud rät, eigene Nutzungsbedingungen anzugeben, statt von CC0 auszugehen. Für `fuzzy-sl` also beim Betreiber bestätigen; hat eine Wikibase eine andere Lizenz, steht sie als `license` in `site.yaml`.
- **Logo von `fuzzy-sl`:** Die Rohdaten enthalten kein Logo und die Sandbox erreicht den Host nicht. Die Datei kommt von Hand ins Demo-Repo und wird in `site.yaml` als `logo` eingetragen (kein Abruf von der Quell-Wikibase, A2).
- **Mehrere Wikibases in einer Seite:** vorerst nicht vorgesehen.
- **w3id-Präfix** für die Dummy-Wikibase und Content Negotiation: offen, erst relevant ab S6/S9.
