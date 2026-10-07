"""Ingredient alias expansion: MFDS API when configured, KCIA-checked local glossary otherwise."""
import io
import json
import os
import unittest
from unittest.mock import patch

from kbeauty_gate import ingredients
from kbeauty_gate.config import Settings
from kbeauty_gate.planner import rank_products

MFDS_ENV = {"MFDS_API_KEY": "abc%2Bdef%3D%3D",
            "MFDS_INGREDIENT_URL": "https://apis.data.go.kr/1471000/TestService/getTestList"}


def offline():
    return Settings("", "https://unused.invalid/chat", ["mock-model"], "https://unused.invalid/embed", "mock-embed", 1)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class LocalGlossaryTests(unittest.TestCase):
    def setUp(self):
        ingredients.reset_cache()

    @patch.dict(os.environ, {}, clear=True)
    def test_fragrance_expands_to_standard_aliases(self):
        terms = ingredients.expand_avoid(["fragrance"])
        self.assertTrue({"fragrance", "perfume", "parfum", "향료"} <= terms)
        self.assertEqual(ingredients.last_source(), "local")

    @patch.dict(os.environ, {}, clear=True)
    def test_korean_request_finds_english_names(self):
        self.assertIn("fragrance", ingredients.expand_avoid(["향료"]))
        self.assertIn("alcohol denat", ingredients.expand_avoid(["변성알코올"]))

    @patch.dict(os.environ, {}, clear=True)
    def test_unknown_word_is_kept_as_is(self):
        self.assertEqual(ingredients.expand_avoid(["mineral oil"]), {"mineral oil"})

    @patch.dict(os.environ, {}, clear=True)
    @patch("kbeauty_gate.ingredients.urllib.request.urlopen")
    def test_no_key_means_no_network(self, urlopen):
        ingredients.expand_avoid(["fragrance"])
        urlopen.assert_not_called()


class MfdsTests(unittest.TestCase):
    def setUp(self):
        ingredients.reset_cache()

    @patch.dict(os.environ, MFDS_ENV, clear=True)
    @patch("kbeauty_gate.ingredients.urllib.request.urlopen")
    def test_api_aliases_are_merged(self, urlopen):
        body = {"header": {"resultCode": "00"},
                "body": {"items": [{"INGR_KOR_NAME": "향료", "INGR_ENG_NAME": "Fragrance", "INGR_SYNONYM": "Aroma, Flavor"}]}}
        urlopen.return_value = FakeResponse(json.dumps(body).encode())
        terms = ingredients.expand_avoid(["fragrance"])
        self.assertIn("aroma", terms)
        self.assertIn("parfum", terms)  # local aliases are kept too
        self.assertEqual(ingredients.last_source(), "mfds")
        url = urlopen.call_args[0][0].full_url
        self.assertTrue(url.startswith("https://apis.data.go.kr/1471000/"))
        # data.go.kr gives an already-encoded key; encoding it again turns % into %25 and auth fails
        self.assertIn("serviceKey=abc%2Bdef%3D%3D&", url)
        self.assertNotIn("%25", url)

    @patch.dict(os.environ, MFDS_ENV, clear=True)
    @patch("kbeauty_gate.ingredients.urllib.request.urlopen", side_effect=OSError("SERVICE_KEY_IS_NOT_REGISTERED_ERROR"))
    def test_api_failure_falls_back_to_glossary(self, urlopen):
        terms = ingredients.expand_avoid(["fragrance"])
        self.assertIn("parfum", terms)
        self.assertEqual(ingredients.last_source(), "local")

    @patch.dict(os.environ, {**MFDS_ENV, "MFDS_INGREDIENT_URL": "https://evil.example.net/x"}, clear=True)
    @patch("kbeauty_gate.ingredients.urllib.request.urlopen")
    def test_only_the_official_host_is_called(self, urlopen):
        ingredients.expand_avoid(["fragrance"])
        urlopen.assert_not_called()


    @patch.dict(os.environ, {**MFDS_ENV, "MFDS_INGREDIENT_URL": "https://apis.data.go.kr/1471057/TestService/getTestList"}, clear=True)
    @patch("kbeauty_gate.ingredients.urllib.request.urlopen")
    def test_second_mfds_agency_path_is_allowed(self, urlopen):
        urlopen.return_value = FakeResponse(b'{"body": {"items": []}}')
        ingredients.expand_avoid(["fragrance"])
        urlopen.assert_called_once()


class PlannerTests(unittest.TestCase):
    def setUp(self):
        ingredients.reset_cache()

    @patch.dict(os.environ, {}, clear=True)
    def test_parfum_is_excluded_when_fragrance_is_avoided(self):
        product = {"id": "T1", "name": "Test Cream", "skin_types": ["dry"], "concerns": ["dryness"],
                   "ingredients": ["water", "parfum"], "ingredients_verified": True, "price_krw": 1000,
                   "category": "cream"}
        picked, excluded = rank_products([product], {"skin_type": "dry", "concerns": ["dryness"],
                                                     "avoid_ingredients": ["fragrance"]}, offline())
        self.assertEqual(picked, [])
        self.assertIn("parfum", excluded[0]["reason"])


if __name__ == "__main__":
    unittest.main()
