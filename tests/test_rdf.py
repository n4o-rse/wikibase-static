"""Tests for the RDF export (S6): the Wikibase data model, DCAT, the Turtle writer, determinism.

    python tests/test_rdf.py

Needs rdflib (requirements.txt) to read the Turtle back. ``tests/fixtures/entities/`` holds Q1 with one statement
for each supported datatype (one qualifier, one reference, one preferred rank) and its target Q2.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "py"))

import rdflib  # noqa: E402
from rdflib import Literal, URIRef  # noqa: E402

from wikibase_static import rdf  # noqa: E402
from wikibase_static.loader import Site, load_site  # noqa: E402
from wikibase_static.model import Entity, Snak, Statement  # noqa: E402

BASE = "https://wb.example.org"
NS = rdf.Namespaces(BASE)
WD, WDT, WDV = NS.wd, NS.wdt, NS.wdv


def snak(prop: str, vtype: str, value, datatype: str, snaktype: str = "value") -> Snak:
    return Snak(property=prop, snaktype=snaktype, datatype=datatype, vtype=vtype, value=value)


def item_ref(prop: str, target: str) -> Snak:
    return snak(prop, "wikibase-entityid", {"entity-type": "item", "id": target}, "wikibase-item")


def statement(sid: str, main: Snak, rank: str = "normal", qualifiers=None, references=None) -> Statement:
    return Statement(id=sid, mainsnak=main, rank=rank, qualifiers=qualifiers or [], references=references or [])


def site_of(*entities: Entity) -> Site:
    site = Site()
    for entity in entities:
        site.entities[entity.id] = entity
    return site


def prop(pid: str, datatype: str) -> Entity:
    return Entity(id=pid, kind="property", datatype=datatype, labels={"en": f"prop {pid}"})


def graph_of(site: Site, catalog=None) -> rdflib.Graph:
    result = rdf.build(site, NS, "https://creativecommons.org/publicdomain/zero/1.0/", catalog)
    graph = rdflib.Graph()
    graph.parse(data=rdf.ntriples(result.triples), format="nt")
    return graph


def U(text: str) -> URIRef:
    return URIRef(text)


# --------------------------------------------------------------------------- terms and syntax


class TermTests(unittest.TestCase):
    def test_literals_are_escaped_for_ntriples(self) -> None:
        self.assertEqual(rdf.escape_literal('a "q" \\ b\nc\td\x01'), 'a \\"q\\" \\\\ b\\nc\\td\\u0001')
        self.assertEqual(rdf.nt(rdf.Lit("x", lang="de")), '"x"@de')
        self.assertEqual(rdf.nt(rdf.Lit("1", rdf.XSD + "integer")), '"1"^^<http://www.w3.org/2001/XMLSchema#integer>')
        self.assertEqual(rdf.nt(rdf.Blank("b1")), "_:b1")

    def test_an_iri_never_contains_a_character_turtle_forbids(self) -> None:
        self.assertEqual(rdf.iri("https://x.org/a b<c>").value, "https://x.org/a%20b%3Cc%3E")

    def test_language_codes_become_bcp47_tags(self) -> None:
        self.assertEqual(rdf.bcp47("zh-hans"), "zh-Hans")
        self.assertEqual(rdf.bcp47("pt-br"), "pt-BR")
        self.assertEqual(rdf.bcp47("de"), "de")

    def test_the_file_name_comes_from_the_host(self) -> None:
        self.assertEqual(rdf.file_stem("https://fuzzy-sl.wikibase.cloud"), "fuzzy-sl.wikibase.cloud")
        self.assertEqual(rdf.file_stem("https://x.org/wiki/"), "x.org-wiki")
        self.assertEqual(rdf.file_stem(rdf.PLACEHOLDER_BASE), "wikibase.example")

    def test_namespaces_follow_the_wikibase_layout(self) -> None:
        self.assertEqual(NS.wd, BASE + "/entity/")
        self.assertEqual(NS.wdt, BASE + "/prop/direct/")
        self.assertEqual(NS.psv, BASE + "/prop/statement/value/")
        self.assertEqual(NS.data, BASE + "/wiki/Special:EntityData/")
        self.assertEqual(rdf.Namespaces(BASE + "/").wd, NS.wd)


class DateTests(unittest.TestCase):
    def test_month_and_day_zero_are_one(self) -> None:
        self.assertEqual(rdf.standard_datetime("+2020-00-00T00:00:00Z", 9, rdf.GREGORIAN), "2020-01-01T00:00:00Z")
        self.assertEqual(rdf.standard_datetime("+2020-05-00T00:00:00Z", 10, rdf.GREGORIAN), "2020-05-01T00:00:00Z")

    def test_a_day_past_the_end_of_the_month_is_clamped(self) -> None:
        self.assertEqual(rdf.standard_datetime("+2021-02-31T00:00:00Z", 11, rdf.GREGORIAN), "2021-02-28T00:00:00Z")
        self.assertEqual(rdf.standard_datetime("+2020-02-31T00:00:00Z", 11, rdf.GREGORIAN), "2020-02-29T00:00:00Z")

    def test_years_before_the_common_era_use_xsd_numbering(self) -> None:
        # 44 BCE (Wikibase: -0044) is year -0043 in XSD 1.1, which has a year 0.
        self.assertEqual(rdf.standard_datetime("-0044-03-15T00:00:00Z", 11, rdf.GREGORIAN), "-0043-03-15T00:00:00Z")
        self.assertEqual(rdf.standard_datetime("-0001-01-01T00:00:00Z", 11, rdf.GREGORIAN), "0000-01-01T00:00:00Z")

    def test_julian_dates_are_converted_at_day_precision(self) -> None:
        self.assertEqual(rdf.standard_datetime("+1582-10-04T00:00:00Z", 11, rdf.JULIAN), "1582-10-14T00:00:00Z")
        self.assertEqual(rdf.standard_datetime("+2000-01-01T00:00:00Z", 11, rdf.JULIAN), "2000-01-14T00:00:00Z")

    def test_year_zero_and_unknown_calendars_have_no_standard_form(self) -> None:
        self.assertIsNone(rdf.standard_datetime("+0000-01-01T00:00:00Z", 11, rdf.GREGORIAN))
        self.assertIsNone(rdf.standard_datetime("+2000-01-01T00:00:00Z", 11, "http://example.org/calendar"))


# --------------------------------------------------------------------------- the data model


class ModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.site = load_site(raw=HERE / "fixtures", derived=HERE / "fixtures" / "nothing")
        self.result = rdf.build(self.site, NS, "https://creativecommons.org/publicdomain/zero/1.0/")
        self.graph = graph_of(self.site)

    def test_the_fixture_exports_without_problems(self) -> None:
        self.assertEqual(self.result.problems, [])
        self.assertEqual(self.result.entities, 12)
        self.assertEqual(self.result.statements, 11)

    def test_entities_are_typed_and_carry_terms_in_the_four_predicates(self) -> None:
        q1 = U(WD + "Q1")
        self.assertIn((q1, rdflib.RDF.type, U(rdf.WIKIBASE + "Item")), self.graph)
        self.assertIn((U(WD + "P1"), rdflib.RDF.type, U(rdf.WIKIBASE + "Property")), self.graph)
        labels = {str(o) for o in self.graph.objects(q1, rdflib.RDFS.label)}
        self.assertTrue(labels)
        for predicate in (rdf.SKOS + "prefLabel", rdf.SCHEMA + "name"):
            self.assertEqual({str(o) for o in self.graph.objects(q1, U(predicate))}, labels)
        self.assertIn(Literal("Sample site", lang="en"), set(self.graph.objects(q1, U(rdf.SKOS + "altLabel"))))

    def test_a_statement_has_node_rank_value_qualifier_and_reference(self) -> None:
        wds = U(NS.wds + "Q1-fixture-1")
        q1 = U(WD + "Q1")
        g = self.graph
        self.assertIn((q1, U(NS.p + "P1"), wds), g)
        self.assertIn((wds, rdflib.RDF.type, U(rdf.WIKIBASE + "Statement")), g)
        self.assertIn((wds, U(rdf.WIKIBASE + "rank"), U(rdf.WIKIBASE + "PreferredRank")), g)
        self.assertIn((wds, rdflib.RDF.type, U(rdf.WIKIBASE + "BestRank")), g)
        self.assertIn((wds, U(NS.ps + "P1"), U(WD + "Q2")), g)
        self.assertIn((q1, U(WDT + "P1"), U(WD + "Q2")), g)
        self.assertEqual(len(list(g.objects(wds, U(NS.pq + "P2")))), 1)
        references = list(g.objects(wds, U(rdf.PROV + "wasDerivedFrom")))
        self.assertEqual(len(references), 1)
        self.assertIn((references[0], rdflib.RDF.type, U(rdf.WIKIBASE + "Reference")), g)
        self.assertIn((references[0], U(NS.pr + "P4"), U("https://example.org/source")), g)

    def test_time_quantity_and_coordinate_get_value_nodes(self) -> None:
        g = self.graph
        for predicate_ns, kind in ((NS.psv, "TimeValue"), (NS.psv, "QuantityValue"), (NS.psv, "GlobecoordinateValue")):
            nodes = {o for s, p, o in g if str(p).startswith(predicate_ns)}
            self.assertTrue(any((n, rdflib.RDF.type, U(rdf.WIKIBASE + kind)) in g for n in nodes), kind)
        nodes = [s for s in g.subjects(rdflib.RDF.type, U(rdf.WIKIBASE + "GlobecoordinateValue"))]
        self.assertTrue(str(nodes[0]).startswith(WDV))
        self.assertTrue(any(str(o).startswith("Point(") for o in g.objects(None, U(NS.wdt + "P6"))) or
                        any(str(o).startswith("Point(") for _s, _p, o in g if isinstance(o, Literal) and o.datatype == U(rdf.GEO + "wktLiteral")))

    def test_the_simple_values_have_their_rdf_datatypes(self) -> None:
        g = self.graph
        times = [o for _s, p, o in g if str(p).startswith(NS.ps + "P") and isinstance(o, Literal) and o.datatype == rdflib.XSD.dateTime]
        self.assertTrue(times)
        decimals = [o for _s, _p, o in g if isinstance(o, Literal) and o.datatype == rdflib.XSD.decimal]
        self.assertTrue(decimals)
        self.assertTrue(any(isinstance(o, Literal) and o.language for _s, p, o in g if str(p).startswith(NS.ps)))
        self.assertTrue(any(str(o).startswith("http://commons.wikimedia.org/wiki/Special:FilePath/") for o in g.objects(None, None)))

    def test_a_property_is_defined_the_way_wikibase_defines_it(self) -> None:
        g = self.graph
        p1 = U(WD + "P1")
        self.assertIn((p1, U(rdf.WIKIBASE + "propertyType"), U(rdf.WIKIBASE + "WikibaseItem")), g)
        self.assertIn((p1, U(rdf.WIKIBASE + "directClaim"), U(NS.wdt + "P1")), g)
        self.assertIn((p1, U(rdf.WIKIBASE + "claim"), U(NS.p + "P1")), g)
        self.assertIn((p1, U(rdf.WIKIBASE + "statementProperty"), U(NS.ps + "P1")), g)
        self.assertIn((U(NS.wdt + "P1"), rdflib.RDF.type, rdflib.OWL.ObjectProperty), g)
        self.assertIn((U(NS.wdt + "P2"), rdflib.RDF.type, rdflib.OWL.DatatypeProperty), g)
        self.assertIn((U(NS.p + "P2"), rdflib.RDF.type, rdflib.OWL.ObjectProperty), g)
        # media and url values are IRIs, so those direct properties are object properties
        types = {str(o): s for s, o in ((s, o) for s, _p, o in g.triples((None, U(rdf.WIKIBASE + "propertyType"), None)))}
        self.assertIn(rdf.WIKIBASE + "CommonsMedia", types)

    def test_every_entity_has_its_dataset_node(self) -> None:
        g = self.graph
        data = U(NS.data + "Q1")
        self.assertIn((data, rdflib.RDF.type, U(rdf.SCHEMA + "Dataset")), g)
        self.assertIn((data, U(rdf.SCHEMA + "about"), U(WD + "Q1")), g)
        self.assertEqual(len(list(g.subjects(rdflib.RDF.type, U(rdf.SCHEMA + "Dataset")))), 12)

    def test_the_turtle_reads_back_as_the_same_graph(self) -> None:
        text = rdf.to_turtle(self.result.triples, NS, "header line")
        parsed = rdflib.Graph()
        parsed.parse(data=text, format="turtle")
        self.assertEqual(len(parsed), len(self.result.triples))
        self.assertTrue(parsed.isomorphic(self.graph))
        self.assertTrue(text.startswith("# header line\n"))


class RankTests(unittest.TestCase):
    def build(self, ranks: list[str]) -> rdflib.Graph:
        statements = [statement(f"Q1$s{i}", item_ref("P1", "Q2"), rank) for i, rank in enumerate(ranks)]
        q1 = Entity(id="Q1", kind="item", labels={"en": "one"}, statements=statements)
        return graph_of(site_of(q1, Entity(id="Q2", kind="item"), prop("P1", "wikibase-item")))

    def count(self, graph: rdflib.Graph, predicate: str) -> int:
        return len(list(graph.triples((U(WD + "Q1"), U(predicate), None))))

    def test_only_the_preferred_statements_are_best_when_there_is_one(self) -> None:
        g = self.build(["normal", "preferred", "deprecated"])
        self.assertEqual(len(list(g.subjects(rdflib.RDF.type, U(rdf.WIKIBASE + "BestRank")))), 1)
        self.assertEqual(self.count(g, WDT + "P1"), 1)

    def test_all_normal_statements_are_best(self) -> None:
        g = self.build(["normal", "normal"])
        self.assertEqual(len(list(g.subjects(rdflib.RDF.type, U(rdf.WIKIBASE + "BestRank")))), 2)

    def test_deprecated_statements_are_never_best(self) -> None:
        g = self.build(["deprecated"])
        self.assertEqual(len(list(g.subjects(rdflib.RDF.type, U(rdf.WIKIBASE + "BestRank")))), 0)
        self.assertEqual(self.count(g, WDT + "P1"), 0)
        self.assertEqual(self.count(g, NS.p + "P1"), 1)


class SnakTests(unittest.TestCase):
    def export(self, *snaks: Snak, extra=()) -> tuple[rdf.Rdf, rdflib.Graph]:
        statements = [statement(f"Q1$s{i}", s) for i, s in enumerate(snaks)]
        entities = [Entity(id="Q1", kind="item", statements=statements), *extra]
        types = {s.property: s.datatype for s in snaks if s.datatype}
        entities += [prop(pid, dt) for pid, dt in types.items()]
        site = site_of(*entities)
        result = rdf.build(site, NS)
        graph = rdflib.Graph()
        graph.parse(data=rdf.ntriples(result.triples), format="nt")
        return result, graph

    def test_novalue_is_a_type_and_somevalue_a_stable_blank_node(self) -> None:
        none = Snak("P1", "novalue", "string")
        some = Snak("P2", "somevalue", "string")
        _result, g = self.export(none, some)
        self.assertIn((U(WD + "Q1"), rdflib.RDF.type, U(NS.wdno + "P1")), g)
        blanks = [o for o in g.objects(U(WD + "Q1"), U(NS.wdt + "P2"))]
        self.assertEqual(len(blanks), 1)
        self.assertIsInstance(blanks[0], rdflib.BNode)

    def test_a_decimal_that_is_not_a_number_is_a_problem_not_a_triple(self) -> None:
        bad = snak("P1", "quantity", {"amount": "many", "unit": "1"}, "quantity")
        result, g = self.export(bad)
        self.assertTrue(any("not a decimal number" in p for p in result.problems))
        self.assertEqual(len(list(g.triples((U(WD + "Q1"), U(NS.wdt + "P1"), None)))), 0)

    def test_a_unit_becomes_an_iri_and_the_unit_one_the_dimensionless_item(self) -> None:
        one = snak("P1", "quantity", {"amount": "+5", "unit": "1"}, "quantity")
        metre = snak("P2", "quantity", {"amount": "+2.5", "unit": "http://www.wikidata.org/entity/Q11573", "upperBound": "+3", "lowerBound": "+2"}, "quantity")
        _result, g = self.export(one, metre)
        units = {str(o) for o in g.objects(None, U(rdf.WIKIBASE + "quantityUnit"))}
        self.assertEqual(units, {rdf.UNIT_ONE, "http://www.wikidata.org/entity/Q11573"})
        self.assertEqual(len(list(g.triples((None, U(rdf.WIKIBASE + "quantityUpperBound"), None)))), 1)

    def test_a_coordinate_on_another_globe_names_the_globe(self) -> None:
        moon = snak("P1", "globecoordinate", {"latitude": 1.5, "longitude": 2.5, "globe": "http://www.wikidata.org/entity/Q405", "precision": 0.1}, "globe-coordinate")
        _result, g = self.export(moon)
        wkt = [str(o) for o in g.objects(U(WD + "Q1"), U(NS.wdt + "P1"))]
        self.assertEqual(wkt, ["<http://www.wikidata.org/entity/Q405> Point(2.5 1.5)"])

    def test_a_coordinate_without_precision_is_auto_precision(self) -> None:
        pt = snak("P1", "globecoordinate", {"latitude": 10, "longitude": 20, "globe": rdf.EARTH, "precision": None}, "globe-coordinate")
        _result, g = self.export(pt)
        self.assertEqual(len(list(g.subjects(rdflib.RDF.type, U(rdf.WIKIBASE + "GeoAutoPrecision")))), 1)

    def test_an_unsupported_datatype_is_counted_not_written(self) -> None:
        odd = snak("P1", "string", "x", "math")
        result, g = self.export(odd)
        self.assertEqual(result.skipped, {"P1": 1})
        self.assertTrue(any("not exported" in p for p in result.problems))
        self.assertEqual(len(list(g.triples((U(WD + "Q1"), U(NS.wdt + "P1"), None)))), 0)

    def test_a_label_in_a_language_code_that_is_no_tag_is_skipped(self) -> None:
        q = Entity(id="Q1", kind="item", labels={"en": "ok", "x y": "bad"})
        result = rdf.build(site_of(q), NS)
        self.assertTrue(any("not a valid tag" in p for p in result.problems))
        self.assertFalse(any(isinstance(o, rdf.Lit) and o.lexical == "bad" for _s, _p, o in result.triples))

    def test_the_same_value_gives_the_same_value_node(self) -> None:
        a = snak("P1", "time", {"time": "+2000-01-01T00:00:00Z", "precision": 9, "timezone": 0, "calendarmodel": rdf.GREGORIAN}, "time")
        b = snak("P2", "time", {"time": "+2000-01-01T00:00:00Z", "precision": 9, "timezone": 0, "calendarmodel": rdf.GREGORIAN}, "time")
        _result, g = self.export(a, b)
        self.assertEqual(len(list(g.subjects(rdflib.RDF.type, U(rdf.WIKIBASE + "TimeValue")))), 1)


# --------------------------------------------------------------------------- DCAT


class DcatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.site = load_site(raw=HERE / "fixtures", derived=HERE / "fixtures" / "nothing")
        sizes = {"Q1": 1234, "Q2": 99}
        self.info = rdf.CatalogInfo(title="Test wiki", description="d", license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                                    source_url=BASE, pages_url="https://pages.example.org/site/", modified="2026-01-01T00:00:00Z",
                                    json_sizes=sizes, export_file="downloads/wb.example.org.ttl", ontology_file="downloads/wikibase-ontology.ttl",
                                    ontology_bytes=5)
        self.result = rdf.build(self.site, NS, None, self.info)
        self.graph = graph_of(self.site, self.info)

    def test_the_wikibase_is_a_catalogue_with_one_per_entity_kind(self) -> None:
        g = self.graph
        root = U(BASE + "/catalog")
        self.assertIn((root, rdflib.RDF.type, U(rdf.DCAT + "Catalog")), g)
        parts = {str(o) for o in g.objects(root, U(rdf.DCTERMS + "hasPart"))}
        self.assertEqual(parts, {NS.cat + "items", NS.cat + "properties"})
        self.assertEqual(len(list(g.objects(U(NS.cat + "items"), U(rdf.DCAT + "dataset")))), 2)
        self.assertEqual(len(list(g.objects(U(NS.cat + "properties"), U(rdf.DCAT + "dataset")))), 10)
        self.assertIn((root, U(rdf.DCTERMS + "conformsTo"), U(rdf.WIKIBASE_ONTOLOGY)), g)

    def test_a_site_with_its_own_uris_has_itself_as_landing_page_and_the_wikibase_only_as_source(self) -> None:
        own = "https://pages.example.org/site"
        info = rdf.CatalogInfo(title="Copy", source_url="https://wb.example.org", pages_url=own + "/", json_sizes={},
                               export_file="downloads/x.ttl", ontology_file="downloads/wikibase-ontology.ttl", ontology_bytes=5)
        ns = rdf.Namespaces(own)
        result = rdf.build(self.site, ns, None, info)
        triples = {(s.value, p.value, o.value) for s, p, o in result.triples if all(isinstance(x, rdf.Iri) for x in (s, p, o))}
        root = own + "/catalog"
        self.assertIn((root, rdf.DCAT + "landingPage", own + "/"), triples)
        self.assertIn((root, rdf.DCTERMS + "source", "https://wb.example.org"), triples)
        self.assertNotIn((root, rdf.DCAT + "landingPage", "https://wb.example.org"), triples)

    def test_a_site_with_the_wikibase_uris_keeps_the_wikibase_as_landing_page(self) -> None:
        triples = {(s.value, p.value, o.value) for s, p, o in self.result.triples if all(isinstance(x, rdf.Iri) for x in (s, p, o))}
        self.assertIn((BASE + "/catalog", rdf.DCAT + "landingPage", BASE), triples)

    def test_every_entity_record_is_a_dataset_beside_its_wikibase_type(self) -> None:
        g = self.graph
        q1 = U(NS.data + "Q1")
        self.assertIn((q1, rdflib.RDF.type, U(rdf.DCAT + "Dataset")), g)
        self.assertIn((q1, rdflib.RDF.type, U(rdf.SCHEMA + "Dataset")), g)
        self.assertIn((q1, U(rdf.DCTERMS + "isPartOf"), U(NS.cat + "items")), g)
        self.assertIn((q1, U(rdf.DCTERMS + "identifier"), Literal("Q1")), g)
        self.assertIn((q1, U(rdf.DCAT + "landingPage"), U("https://pages.example.org/site/Q1.html")), g)
        self.assertEqual(len(list(g.subjects(rdflib.RDF.type, U(rdf.DCAT + "Dataset")))), 12 + 2)

    def test_distributions_are_json_turtle_and_html_with_real_urls(self) -> None:
        g = self.graph
        q1 = U(NS.data + "Q1")
        dists = {str(d): d for d in g.objects(q1, U(rdf.DCAT + "distribution"))}
        self.assertEqual(set(dists), {NS.dist + "Q1-json", NS.dist + "Q1-ttl", NS.dist + "Q1-html"})
        json_d = dists[NS.dist + "Q1-json"]
        self.assertIn((json_d, U(rdf.DCAT + "downloadURL"), U("https://pages.example.org/site/json/Q1.json")), g)
        self.assertIn((json_d, U(rdf.DCAT + "byteSize"), Literal(1234, datatype=rdflib.XSD.nonNegativeInteger)), g)
        self.assertIn((json_d, U(rdf.DCAT + "mediaType"), U(rdf.MEDIA_TYPE + "application/json")), g)
        self.assertIn((dists[NS.dist + "Q1-ttl"], U(rdf.DCAT + "downloadURL"), U("https://pages.example.org/site/ttl/Q1.ttl")), g)
        self.assertIn((dists[NS.dist + "Q1-html"], U(rdf.DCAT + "accessURL"), U("https://pages.example.org/site/Q1.html")), g)

    def test_an_entity_without_an_archived_file_has_no_json_distribution(self) -> None:
        g = self.graph
        self.assertEqual(len(list(g.objects(U(NS.data + "P1"), U(rdf.DCAT + "distribution")))), 2)

    def test_the_export_and_the_ontology_are_datasets_of_the_catalogue(self) -> None:
        g = self.graph
        for key in ("export", "wikibase-ontology"):
            self.assertIn((U(BASE + "/catalog"), U(rdf.DCAT + "dataset"), U(NS.cat + key)), g)
            self.assertEqual(len(list(g.objects(U(NS.cat + key), U(rdf.DCAT + "distribution")))), 1)

    def test_without_pages_url_there_are_no_distributions_and_a_note_says_why(self) -> None:
        info = rdf.CatalogInfo(title="t")
        result = rdf.build(self.site, NS, None, info)
        self.assertEqual(result.distributions, 0)
        self.assertTrue(any("pages_url" in n for n in result.notes))
        g = rdflib.Graph()
        g.parse(data=rdf.ntriples(result.triples), format="nt")
        self.assertEqual(len(list(g.triples((None, U(rdf.DCAT + "distribution"), None)))), 0)
        self.assertIn((U(NS.data + "Q1"), rdflib.RDF.type, U(rdf.DCAT + "Dataset")), g)

    def test_without_a_catalogue_the_export_is_the_plain_wikibase_model(self) -> None:
        plain = graph_of(self.site)
        self.assertEqual(len(list(plain.subjects(rdflib.RDF.type, U(rdf.DCAT + "Dataset")))), 0)

    def test_the_file_of_one_entity_holds_that_entity_and_not_the_others(self) -> None:
        own = self.result.by_entity["Q1"]
        g = rdflib.Graph()
        g.parse(data=rdf.ntriples(own), format="nt")
        self.assertIn((U(WD + "Q1"), rdflib.RDF.type, U(rdf.WIKIBASE + "Item")), g)
        self.assertIn((U(NS.data + "Q1"), rdflib.RDF.type, U(rdf.DCAT + "Dataset")), g)
        self.assertEqual(len(list(g.triples((U(WD + "Q2"), rdflib.RDF.type, None)))), 0)
        self.assertEqual(len(list(g.triples((None, U(rdf.DCAT + "dataset"), None)))), 0)   # catalogue triples stay in the whole file
        self.assertTrue(own < self.result.triples)

    def test_the_entity_files_together_cover_every_entity_triple(self) -> None:
        union = set().union(*self.result.by_entity.values())
        catalogue = {t for t in self.result.triples if t not in union and t not in self.result.crm}      # the CRM section is its own
        own = (NS.cat.rstrip("/"), NS.dist + "export", NS.dist + "wikibase-ontology")
        self.assertTrue(catalogue)
        self.assertTrue(all(t[0].value.startswith(own) for t in catalogue), [t for t in catalogue if not t[0].value.startswith(own)][:3])


# --------------------------------------------------------------------------- determinism


class DeterminismTests(unittest.TestCase):
    def test_two_builds_give_the_same_bytes(self) -> None:
        site = load_site(raw=HERE / "fixtures", derived=HERE / "fixtures" / "nothing")
        info = rdf.CatalogInfo(title="t", pages_url="https://p.example/", json_sizes={"Q1": 1})
        first = rdf.to_turtle(rdf.build(site, NS, None, info).triples, NS, "h")
        second = rdf.to_turtle(rdf.build(site, NS, None, info).triples, NS, "h")
        self.assertEqual(first, second)

    def test_the_order_of_the_entities_does_not_matter(self) -> None:
        loaded = load_site(raw=HERE / "fixtures", derived=HERE / "fixtures" / "nothing")
        reversed_site = Site()
        for key in reversed(list(loaded.entities)):
            reversed_site.entities[key] = loaded.entities[key]
        a = rdf.to_turtle(rdf.build(loaded, NS).triples, NS)
        b = rdf.to_turtle(rdf.build(reversed_site, NS).triples, NS)
        self.assertEqual(a, b)

    def test_the_hash_seed_does_not_change_a_byte(self) -> None:
        code = ("import sys,hashlib;sys.path.insert(0,sys.argv[1]);from pathlib import Path;"
                "from wikibase_static import rdf;from wikibase_static.loader import load_site;"
                "s=load_site(raw=Path(sys.argv[2]),derived=Path(sys.argv[2])/'nothing');ns=rdf.Namespaces('https://wb.example.org');"
                "i=rdf.CatalogInfo(title='t',pages_url='https://p.example/');"
                "print(hashlib.sha256(rdf.to_turtle(rdf.build(s,ns,None,i).triples,ns,'h').encode()).hexdigest())")
        hashes = set()
        for seed in ("0", "1", "42"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            out = subprocess.run([sys.executable, "-c", code, str(HERE.parent / "py"), str(HERE / "fixtures")],
                                 capture_output=True, text=True, env=env, check=True)
            hashes.add(out.stdout.strip())
        self.assertEqual(len(hashes), 1, hashes)

    def test_the_ntriples_are_sorted_lines(self) -> None:
        site = load_site(raw=HERE / "fixtures", derived=HERE / "fixtures" / "nothing")
        lines = rdf.ntriples(rdf.build(site, NS).triples).splitlines()
        self.assertEqual(lines, sorted(lines))
        self.assertTrue(all(line.endswith(" .") for line in lines))

    def test_sorting_is_natural_so_q2_comes_before_q10(self) -> None:
        items = [Entity(id=f"Q{n}", kind="item", labels={"en": str(n)}) for n in (10, 2, 1)]
        text = rdf.to_turtle(rdf.build(site_of(*items), NS).triples, NS)
        self.assertLess(text.index("\nwd:Q1\n"), text.index("\nwd:Q2\n"))
        self.assertLess(text.index("\nwd:Q2\n"), text.index("\nwd:Q10\n"))

    def test_the_ontology_shipped_with_the_package_parses_and_defines_the_terms_we_write(self) -> None:
        path = HERE.parent / "py" / "wikibase_static" / "data" / "wikibase-ontology.ttl"
        g = rdflib.Graph()
        g.parse(path, format="turtle")
        for term in ("Item", "Property", "Statement", "Reference", "BestRank", "PreferredRank", "TimeValue", "QuantityValue",
                     "GlobecoordinateValue", "directClaim", "claim", "rank", "timePrecision", "geoLatitude"):
            self.assertIn((U(rdf.WIKIBASE + term), None, None), g, term)

    def test_the_terms_the_export_uses_that_the_ontology_file_lacks_are_the_known_ones(self) -> None:
        # The ontology.owl of Wikibase is older than its dumper: the dumper writes these four, the file does not
        # define them (PRIMER.md, Befund 23). If this set changes, the file or the export changed: look at both.
        path = HERE.parent / "py" / "wikibase_static" / "data" / "wikibase-ontology.ttl"
        g = rdflib.Graph()
        g.parse(path, format="turtle")
        defined = {str(s)[len(rdf.WIKIBASE):] for s in g.subjects() if str(s).startswith(rdf.WIKIBASE)}
        site = load_site(raw=HERE / "fixtures", derived=HERE / "fixtures" / "nothing")
        used = set()
        for _s, p, o in rdf.build(site, NS).triples:
            for term in (p, o):
                if isinstance(term, rdf.Iri) and term.value.startswith(rdf.WIKIBASE):
                    used.add(term.value[len(rdf.WIKIBASE):])
        self.assertEqual(used - defined, {"GlobeCoordinate", "identifiers", "propertyType", "statements"})


if __name__ == "__main__":
    unittest.main()
