"""The default queries stay usable on a site with many properties (S7b, found on the first run of the chublets demo).

    python tests/test_queries_scale.py

The query "references" once joined the list of all properties with itself before it looked at a single reference:
159 properties made it run for 85 seconds, 36 (fuzzy-sl) for under two. This builds a site of 160 properties, each used
once with a reference, and runs the query through the same runner as the SPARQL page.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "py"))

from wikibase_static import csvbuild, loader, rdf, sparql  # noqa: E402

BASE = "https://example.org"
PROPERTIES = 160
LIMIT_SECONDS = 20      # about one second on a slow machine; the old query needed 85


def site_with_many_properties(properties: int = PROPERTIES, copies: int = 1) -> loader.Site:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        (base / "csv").mkdir()
        entities = "id,kind,datatype,label_en\nQ100,class,,Thing\nQ101,item,,An item\n"
        statements = "sid,subject,property,value\n,Q100,P1,Q3\n,Q101,P2,Q100\n"
        references = "sid,group,property,value\n"
        for n in range(properties):
            entities += f"P{100 + n},property,string,property {n}\n"
        for n in range(properties * copies):
            statements += f"s{n},Q101,P{100 + n % properties},value {n}\n"
            references += f"s{n},1,P6,https://example.org/page/{n}\n"
        for name, text in (("entities.csv", entities), ("statements.csv", statements), ("references.csv", references)):
            (base / "csv" / name).write_text(text, encoding="utf-8")
        problems: list[str] = []
        built = csvbuild.build(csvbuild.read_set(base / "csv", problems, "csv"), csvbuild.kernel_set(), BASE)
        assert not (problems or built.problems), (problems, built.problems)
        folder = base / "derived" / "entities"
        folder.mkdir(parents=True)
        for entity_id, obj in built.entities.items():
            (folder / f"{entity_id}.json").write_text(json.dumps(obj), encoding="utf-8")
        return loader.load_site(base / "none", base / "derived")


class ReferencesQuery(unittest.TestCase):
    def test_it_runs_in_seconds_with_many_properties_and_finds_every_reference(self) -> None:
        site = site_with_many_properties()
        ns = rdf.Namespaces(BASE)
        text = rdf.to_turtle(rdf.build(site, ns).triples, ns)
        queries = sparql.load_queries(None)
        sparql.apply_language(queries, "en")
        wanted = [q for q in queries.queries if q.id == "references"]
        self.assertEqual(len(wanted), 1)
        started = time.time()
        result = sparql.run_all(text, wanted, ns.prefixes())[0]
        elapsed = time.time() - started
        self.assertIsNone(result["error"])
        self.assertEqual(result["rows"], PROPERTIES)
        self.assertLess(elapsed, LIMIT_SECONDS, f"{elapsed:.0f} s for {PROPERTIES} properties")

    def test_it_runs_in_seconds_with_many_referenced_statements(self) -> None:
        """S7c: 1 536 references on 37 000 triples took 22 s (rdflib paired a third group with every row)."""
        site = site_with_many_properties(properties=20, copies=150)
        ns = rdf.Namespaces(BASE)
        text = rdf.to_turtle(rdf.build(site, ns).triples, ns)
        queries = sparql.load_queries(None)
        sparql.apply_language(queries, "en")
        wanted = [q for q in queries.queries if q.id == "references"]
        started = time.time()
        result = sparql.run_all(text, wanted, ns.prefixes())[0]
        elapsed = time.time() - started
        self.assertIsNone(result["error"])
        self.assertEqual(result["rows"], 200)           # the query has LIMIT 200; 3 000 statements are there
        self.assertLess(elapsed, LIMIT_SECONDS, f"{elapsed:.0f} s for 3 000 referenced statements")


if __name__ == "__main__":
    unittest.main()
