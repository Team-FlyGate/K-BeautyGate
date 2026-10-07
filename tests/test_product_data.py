"""Consistency of the synthetic beauty catalogue: products, stores, brand registry and ingredient glossary must agree."""
import csv
import json
from pathlib import Path
import unittest

from kbeauty_gate.config import Settings
from kbeauty_gate.planner import rank_products

BEAUTY = Path(__file__).resolve().parents[1] / "hackathon" / "input" / "beauty"
CONCERNS = {"redness", "dryness", "dullness", "pores", "color", "sun protection"}


def load():
    products = json.loads((BEAUTY / "products" / "products.json").read_text(encoding="utf-8"))
    stores = json.loads((BEAUTY / "stores" / "stores.json").read_text(encoding="utf-8"))
    registry = {r["brand"] for r in csv.DictReader((BEAUTY / "brands" / "kr_brand_registry.csv").open(encoding="utf-8"))}
    glossary = {r["inci"]: r for r in csv.DictReader((BEAUTY / "ingredients" / "ingredient_glossary.csv").open(encoding="utf-8"))}
    return products, stores, registry, glossary


def offline():
    return Settings("", "https://unused.invalid/chat", ["mock-model"], "https://unused.invalid/embed", "mock-embed", 1)


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        self.products, self.stores, self.registry, self.glossary = load()
        self.by_id = {p["id"]: p for p in self.products}

    def test_ids_unique_and_stores_carry_known_products(self):
        self.assertEqual(len(self.by_id), len(self.products))
        for store in self.stores:
            self.assertTrue(set(store["carries"]) <= set(self.by_id), store["id"])

    def test_official_products_are_registered_and_sold_somewhere(self):
        carried = {pid for s in self.stores for pid in s["carries"]}
        for p in self.products:
            if p["source"] == "brand_official":
                self.assertIn(p["brand"], self.registry, p["id"])
                self.assertIn(p["id"], carried, p["id"])

    def test_traps_stay_unregistered(self):
        for pid in ("P07", "P08"):
            self.assertNotIn(self.by_id[pid]["brand"], self.registry)

    def test_concerns_use_known_vocabulary(self):
        for p in self.products:
            self.assertTrue(set(p["concerns"]) <= CONCERNS, p["id"])

    def test_every_ingredient_has_a_korean_name(self):
        known = set(self.glossary) | {alias.strip().lower() for row in self.glossary.values()
                                      for alias in (row.get("kcia_en") or "").split("|") if alias.strip()}
        missing = {i for p in self.products for i in p["ingredients"]} - known
        self.assertEqual(missing, set())

    def test_each_concern_has_at_least_two_official_choices(self):
        for concern in ("redness", "dryness", "dullness", "pores"):
            n = sum(1 for p in self.products if p["source"] == "brand_official" and concern in p["concerns"])
            self.assertGreaterEqual(n, 2, concern)


class ScenarioTests(unittest.TestCase):
    """Different visitors must get different picks, and avoided ingredients must actually split the catalogue."""

    def setUp(self):
        products, _, registry, _ = load()
        self.trusted = [p for p in products if p["brand"] in registry and p["source"] == "brand_official"]

    def pick(self, **profile):
        picked, excluded = rank_products(self.trusted, profile, offline())
        return [r["product"]["id"] for r in picked], excluded

    def test_dry_skin_avoiding_fragrance(self):
        picked, excluded = self.pick(skin_type="dry", concerns=["dryness"], avoid_ingredients=["fragrance"], budget_krw=50000)
        self.assertTrue(picked)
        self.assertFalse({"P10", "P18"} & set(picked))
        self.assertTrue(any("fragrance" in e["reason"] for e in excluded))

    def test_oily_pores_differs_from_dry(self):
        oily, _ = self.pick(skin_type="oily", concerns=["pores"], budget_krw=50000)
        dry, _ = self.pick(skin_type="dry", concerns=["dryness"], budget_krw=50000)
        self.assertTrue({"P15", "P16"} & set(oily))
        self.assertNotEqual(set(oily), set(dry))

    def test_small_budget_still_gets_a_pick(self):
        picked, _ = self.pick(skin_type="sensitive", concerns=["redness"], budget_krw=10000)
        self.assertTrue(picked)
        self.assertIn("P19", picked)


if __name__ == "__main__":
    unittest.main()
