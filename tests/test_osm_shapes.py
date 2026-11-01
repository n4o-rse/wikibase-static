"""Tests for the shapes of ways and relations (S15b/S6): WKT, the shape at each moment, the import, the member fetch, GeoSPARQL, the map.

    python tests/test_osm_shapes.py

Standard library plus rdflib. All geometry here is **synthetic** (small squares near 53 N, 6 W, invented ids); no real element is
copied. A real way and a real multipolygon are fetched with ``import-osm --element`` and checked by hand (PRIMER, S6).
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "py"))
sys.path.insert(0, str(HERE))

import rdflib  # noqa: E402

from wikibase_static import osm_geom, rdf, wkt  # noqa: E402
from wikibase_static.model import Entity, Snak, Statement  # noqa: E402
from wikibase_static.render import Renderer  # noqa: E402
from wikibase_static.loader import Site as LoadedSite  # noqa: E402
from wikibase_static.site_config import SiteConfig  # noqa: E402
import test_import_osm as base  # noqa: E402
import test_import_osm_net as net  # noqa: E402

T1, T2, T3 = "2020-01-01T00:00:00Z", "2021-06-01T00:00:00Z", "2022-03-01T00:00:00Z"


def node(number: int, *versions: tuple[str, float, float]) -> dict:
    return {"version": "0.6", "elements": [
        {"type": "node", "id": number, "version": i, "timestamp": t, "changeset": 1, "user": "u", "uid": 1, "lat": lat, "lon": lon}
        for i, (t, lat, lon) in enumerate(versions, start=1)]}


def way(number: int, nodes: list[int], tags: dict, *stamps: str) -> dict:
    return {"version": "0.6", "elements": [
        {"type": "way", "id": number, "version": i, "timestamp": t, "changeset": 1, "user": "u", "uid": 1, "nodes": nodes, "tags": tags}
        for i, t in enumerate(stamps, start=1)]}


def relation(number: int, members: list[tuple[str, int, str]], tags: dict, *stamps: str) -> dict:
    return {"version": "0.6", "elements": [
        {"type": "relation", "id": number, "version": i, "timestamp": t, "changeset": 1, "user": "u", "uid": 1, "tags": tags,
         "members": [{"type": k, "ref": r, "role": role} for k, r, role in members]} for i, t in enumerate(stamps, start=1)]}


def world() -> dict[str, dict]:
    """Way 10: a closed building on nodes 1-4 (node 3 moves in 2021); way 11 and 12: outer and inner ring of relation 20; way 13: a road."""
    files: dict[str, dict] = {}
    for number, lat, lon in ((1, 53.0, -6.0), (2, 53.0, -5.9), (4, 53.1, -6.0)):
        files[f"node/{number}"] = node(number, (T1, lat, lon))
    files["node/3"] = node(3, (T1, 53.1, -5.9), (T2, 53.2, -5.9))
    files["way/10"] = way(10, [1, 2, 3, 4, 1], {"building": "yes"}, T1)
    for number, (lat, lon) in zip((5, 6, 7, 8), ((54.0, -6.0), (54.0, -5.0), (55.0, -5.0), (55.0, -6.0))):
        files[f"node/{number}"] = node(number, (T1, lat, lon))
    for number, (lat, lon) in zip((15, 16, 17, 18), ((54.2, -5.8), (54.2, -5.6), (54.4, -5.6), (54.4, -5.8))):
        files[f"node/{number}"] = node(number, (T1, lat, lon))
    files["way/11"] = way(11, [5, 6, 7], {}, T1)            # the outer ring comes in two pieces
    files["way/14"] = way(14, [7, 8, 5], {}, T1)
    files["way/12"] = way(12, [15, 16, 17, 18, 15], {}, T1)
    files["relation/20"] = relation(20, [("way", 11, "outer"), ("way", 14, "outer"), ("way", 12, "inner")],
                                    {"type": "multipolygon", "man_made": "survey_point", "benchmark": "yes"}, T1, T3)
    files["way/13"] = way(13, [1, 2, 3, 1], {"highway": "path"}, T1)
    return files


def write(folder: Path, files: dict[str, dict]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for key, data in files.items():
        (folder / (key.replace("/", "_") + ".json")).write_text(json.dumps(data), encoding="utf-8")


class WktTests(unittest.TestCase):
    def test_write_and_read_back(self) -> None:
        ring = [(-6.0, 53.0), (-5.9, 53.0), (-5.9, 53.1), (-6.0, 53.0)]
        self.assertEqual(wkt.polygon([ring]), "POLYGON((-6 53, -5.9 53, -5.9 53.1, -6 53))")
        self.assertEqual(wkt.parse(wkt.polygon([ring]))["coordinates"][0][1], [-5.9, 53.0])
        self.assertEqual(wkt.point((-6.0906724, 53.3909747)), "POINT(-6.0906724 53.3909747)")

    def test_reads_every_kind_in_any_case_and_skips_a_crs_iri(self) -> None:
        for text, kind in (("point(1 2)", "Point"), ("LINESTRING(0 0, 1 1)", "LineString"), ("MULTIPOINT((1 2), (3 4))", "MultiPoint"),
                           ("MULTILINESTRING((0 0, 1 1), (2 2, 3 3))", "MultiLineString"),
                           ("MULTIPOLYGON(((0 0, 1 0, 1 1, 0 0)), ((5 5, 6 5, 6 6, 5 5)))", "MultiPolygon"),
                           ("GEOMETRYCOLLECTION(POINT(1 2), LINESTRING(0 0, 1 1))", "GeometryCollection"),
                           ("<http://www.opengis.net/def/crs/OGC/1.3/CRS84> POINT(1 2)", "Point")):
            self.assertEqual(wkt.parse(text)["type"], kind, text)

    def test_refuses_what_is_no_geometry(self) -> None:
        for text in ("POINT(1)", "POINT(200 0)", "LINE(1 2)", "POINT EMPTY", "POINT(1 2) x", "POLYGON((0 0, 1 1)", ""):
            with self.assertRaises(wkt.WktError, msg=text):
                wkt.parse(text)

    def test_centre_is_the_middle_of_the_bounding_box(self) -> None:
        self.assertEqual(wkt.centre(wkt.parse("POLYGON((0 0, 2 0, 2 4, 0 0))")), (2.0, 1.0))


class ShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        write(self.dir, world())
        self.store = osm_geom.Store(self.dir)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def events(self, key: str):
        return osm_geom.events(key.split("/")[0], self.store.versions(key), self.store)

    def test_a_moved_node_changes_the_shape_though_the_way_keeps_its_version(self) -> None:
        result = self.events("way/10")
        self.assertEqual([(e.time, e.version) for e in result.events], [(T1, 1), (T2, 1)])
        self.assertEqual(result.events[0].wkt, "POLYGON((-6 53, -5.9 53, -5.9 53.1, -6 53.1, -6 53))")
        self.assertEqual(result.events[1].wkt, "POLYGON((-6 53, -5.9 53, -5.9 53.2, -6 53.1, -6 53))")
        self.assertEqual((result.missing, result.notes), (set(), set()))

    def test_a_closed_highway_is_a_line_and_a_closed_building_an_area(self) -> None:
        self.assertTrue(self.events("way/13").events[0].wkt.startswith("LINESTRING"))
        self.assertTrue(self.events("way/10").events[0].wkt.startswith("POLYGON"))
        self.assertTrue(osm_geom.is_area({"highway": "pedestrian", "area": "yes"}, True))
        self.assertFalse(osm_geom.is_area({"building": "yes", "area": "no"}, True))
        self.assertFalse(osm_geom.is_area({"building": "yes"}, False))

    def test_a_multipolygon_joins_its_pieces_and_takes_the_hole(self) -> None:
        result = self.events("relation/20")
        self.assertEqual(len(result.events), 1)
        shape = wkt.parse(result.events[0].wkt)
        self.assertEqual(shape["type"], "Polygon")
        self.assertEqual(len(shape["coordinates"]), 2)                       # outer ring and one inner ring
        self.assertEqual(len(shape["coordinates"][0]), 5)                    # the two pieces became one closed ring
        self.assertEqual(result.events[0].version, 1)

    def test_two_outer_rings_make_a_multipolygon(self) -> None:
        ring = osm_geom.area_shape([[(0, 0), (1, 0), (1, 1), (0, 0)], [(5, 5), (6, 5), (6, 6), (5, 5)]], [])
        self.assertTrue(ring.startswith("MULTIPOLYGON"))

    def test_an_open_ring_gives_no_shape_and_a_note(self) -> None:
        files = world()
        files["relation/21"] = relation(21, [("way", 11, "outer")], {"type": "multipolygon"}, T1)
        write(self.dir, files)
        store = osm_geom.Store(self.dir)
        result = osm_geom.events("relation", store.versions("relation/21"), store)
        self.assertEqual(result.events, [])
        self.assertTrue(any("does not close" in n for n in result.notes))

    def test_another_relation_is_lines_and_points(self) -> None:
        files = world()
        files["relation/22"] = relation(22, [("way", 13, ""), ("node", 4, "stop")], {"type": "route"}, T1)
        write(self.dir, files)
        store = osm_geom.Store(self.dir)
        result = osm_geom.events("relation", store.versions("relation/22"), store)
        self.assertTrue(result.events[0].wkt.startswith("GEOMETRYCOLLECTION(MULTILINESTRING("))

    def test_missing_members_are_named_not_guessed(self) -> None:
        (self.dir / "node_3.json").unlink()
        store = osm_geom.Store(self.dir)
        result = osm_geom.events("way", store.versions("way/10"), store)
        self.assertEqual(result.events, [])
        self.assertEqual(result.missing, {"node/3"})

    def test_member_keys_follow_a_relation_to_the_nodes_of_its_ways(self) -> None:
        keys = osm_geom.member_keys("relation", self.store.versions("relation/20"), self.store)
        self.assertEqual(keys, {"way/11", "way/14", "way/12", *(f"node/{n}" for n in (5, 6, 7, 8, 15, 16, 17, 18))})


class ImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.site = base.Site(history=False)
        self.members = self.site.root / "data" / "raw" / "osm" / "members"
        files = world()
        for key in ("way/10", "relation/20"):                  # the selected elements; their members are in the members folder
            kind, number = key.split("/")
            (self.site.history / f"{kind}_{number}.json").write_text(json.dumps(files.pop(key)), encoding="utf-8")
        write(self.members, files)

    def tearDown(self) -> None:
        self.site.close()

    def statements(self, prop: str) -> list[dict[str, str]]:
        return base.rows(self.site.csv / "statements.csv") and [r for r in base.rows(self.site.csv / "statements.csv") if r["property"] == prop]

    def test_way_and_relation_become_items_with_a_shape_history(self) -> None:
        code, out = self.site.run()
        self.assertEqual(code, 0, out)
        shapes = self.statements("P111")
        self.assertEqual([r["sid"].split("-")[-1] for r in shapes if r["subject"] == "Q102"], ["g1", "g2"])
        self.assertEqual(len([r for r in shapes if r["subject"] == "Q101"]), 1)   # the relation (files sort by name)
        coordinate = [r["value"] for r in self.statements("P110") if r["subject"] == "Q102"]
        self.assertEqual(coordinate, ["53.1,-5.95"])                      # the middle of the box of the last shape
        qualifiers = [r for r in base.rows(self.site.csv / "qualifiers.csv") if r["sid"] == "Q102-P111-g2"]
        self.assertEqual({(q["property"], q["value"]) for q in qualifiers}, {("P102", "1"), ("P103", T2)})
        self.assertIn("items: 2 (1 relation, 1 way)", out)

    def test_a_second_import_changes_nothing(self) -> None:
        self.site.run()
        before = {p.name: p.read_bytes() for p in self.site.csv.glob("*.csv")}
        self.site.run()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.site.csv.glob("*.csv")})


class MemberFetchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.site = net.Site()
        for key, data in world().items():
            self.site.fake.histories[key] = json.dumps(data).encode("utf-8")
        self.members = self.site.root / "data" / "raw" / "osm" / "members"

    def tearDown(self) -> None:
        self.site.close()

    def test_element_fetches_the_way_and_its_nodes_without_asking_overpass(self) -> None:
        code, out = self.site.run("--element", "way/10")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.site.fake.kinds().count("overpass"), 0)
        self.assertEqual(sorted(k for kind, k in self.site.fake.log if kind == "history"), ["node/1", "node/2", "node/3", "node/4", "way/10"])
        self.assertEqual(sorted(p.name for p in self.members.glob("*.json")), ["node_1.json", "node_2.json", "node_3.json", "node_4.json"])
        self.assertEqual((self.site.history / "way_10.json").read_bytes(), self.site.fake.histories["way/10"])
        self.assertIn("member histories", out)

    def test_a_relation_takes_two_rounds_ways_then_their_nodes(self) -> None:
        code, out = self.site.run("--element", "relation/20")
        self.assertEqual(code, 0, out)
        names = sorted(p.stem for p in self.members.glob("*.json"))
        self.assertEqual(len(names), 11)
        shapes = [r for r in base.rows(self.site.csv / "statements.csv") if r["property"] == "P111"]
        self.assertEqual(len(shapes), 1)

    def test_a_second_run_asks_for_no_member_again_and_refresh_compares(self) -> None:
        self.site.run("--element", "way/10")
        before = {p.name: p.read_bytes() for p in self.members.glob("*.json")}
        self.site.fake.log.clear()
        self.site.run("--element", "way/10")
        self.assertEqual([k for kind, k in self.site.fake.log if kind == "history" and k.startswith("node/")], [])
        self.site.fake.log.clear()
        _, out = self.site.run("--element", "way/10", "--refresh")
        self.assertEqual(len([1 for kind, k in self.site.fake.log if kind == "history" and k.startswith("node/")]), 4)
        self.assertIn("4 stored member histories agree with the API in the versions they share, 0 differ", out)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.members.glob("*.json")})

    def test_member_limit_leaves_the_rest_for_the_next_run(self) -> None:
        _, out = self.site.run("--element", "way/10", "--member-limit", "2")
        self.assertEqual(len(list(self.members.glob("*.json"))), 2)
        self.assertIn("2 left for the next run (--member-limit 2)", out)
        _, out = self.site.run("--element", "way/10", "--member-limit", "2")
        self.assertEqual(len(list(self.members.glob("*.json"))), 4)

    def test_bad_element_names_are_refused(self) -> None:
        code, out = self.site.run("--element", "way/x")
        self.assertEqual(code, 2)
        self.assertIn("is not node/<id>, way/<id> or relation/<id>", out)


def string_statement(sid: str, value: str, rank: str = "normal") -> Statement:
    return Statement(id=sid, mainsnak=Snak(property="P111", snaktype="value", datatype="string", vtype="string", value=value), rank=rank)


class RdfAndMapTests(unittest.TestCase):
    SQUARE = "POLYGON((-6 53, -5.9 53, -5.9 53.1, -6 53))"

    def site(self) -> LoadedSite:
        site = LoadedSite()
        site.entities["P111"] = Entity(id="P111", kind="property", datatype="string", labels={"en": "shape"})
        site.entities["Q1"] = Entity(id="Q1", kind="item", labels={"en": "Square"}, statements=[
            string_statement("Q1-1", "POINT(-6 53)"), string_statement("Q1-2", self.SQUARE), string_statement("Q1-3", "not wkt")])
        return site

    def graph(self, wkt_property):
        ns = rdf.Namespaces("https://wb.example.org")
        result = rdf.build(self.site(), ns, "https://creativecommons.org/publicdomain/zero/1.0/", None, None, wkt_property)
        graph = rdflib.Graph()
        graph.parse(data=rdf.ntriples(result.triples), format="nt")
        return ns, result, graph

    def test_geosparql_for_every_wkt_entry(self) -> None:
        ns, result, graph = self.graph("P111")
        item = rdflib.URIRef(ns.wd + "Q1")
        geo = rdflib.Namespace(rdf.GEO)
        self.assertIn((item, rdflib.RDF.type, geo.Feature), graph)
        geometries = set(graph.objects(item, geo.hasGeometry))
        self.assertEqual(len(geometries), 2)                                  # the third value is not WKT
        for node in geometries:
            self.assertIn((node, rdflib.RDF.type, geo.Geometry), graph)
            self.assertEqual(next(graph.objects(node, geo.asWKT)).datatype, rdflib.URIRef(rdf.GEO + "wktLiteral"))
        default = list(graph.objects(item, geo.hasDefaultGeometry))
        self.assertEqual(len(default), 1)
        self.assertEqual(str(next(graph.objects(default[0], geo.asWKT))), self.SQUARE)
        self.assertTrue(any("is not WKT" in p for p in result.problems))

    def test_without_the_setting_nothing_changes(self) -> None:
        _, result, graph = self.graph(None)
        self.assertEqual(list(graph.subjects(rdflib.RDF.type, rdflib.URIRef(rdf.GEO + "Feature"))), [])
        self.assertEqual(result.problems, [])

    def test_the_map_gets_the_last_shape_but_not_a_point(self) -> None:
        site = self.site()
        r = Renderer(site, SiteConfig(wkt_property="P111"), "test")
        site.entities["Q1"].statements = [string_statement("Q1-1", "POINT(-6 53)")]
        self.assertEqual(r.map_shapes(site.entities["Q1"]), [])
        site.entities["Q1"].statements.append(string_statement("Q1-2", self.SQUARE))
        shapes = r.map_shapes(site.entities["Q1"])
        self.assertEqual(shapes[0]["geometry"]["type"], "Polygon")
        self.assertEqual(Renderer(site, SiteConfig(), "test").map_shapes(site.entities["Q1"]), [])


if __name__ == "__main__":
    unittest.main()
