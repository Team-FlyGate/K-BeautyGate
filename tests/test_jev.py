"""Keep optional judgment scores additive to the local rules, without external I/O."""
import io
import json
from contextlib import ExitStack
from datetime import date
from http.client import BadStatusLine, IncompleteRead
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from kbeauty_gate import jev
from kbeauty_gate.collect import collect
from kbeauty_gate.guard import AuditLog, SafeFS
from kbeauty_gate.request_guard import MESSAGES, screen_request
from test_scenarios import SCENARIOS, run_local_scenario


def request_result(p=0.8, kind="external_send"):
    return {"answers": {"unsafe": {"noul": p}, "kind": {"choice": kind}}, "model": "fixture"}


def document_result(inject=0.0, ad=0.0):
    return {"answers": {"d0_inject": {"noul": inject}, "d0_ad": {"noul": ad}}, "model": "fixture"}


class NoExternalIO(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict("os.environ", {"KBG_OPENSHELL_PROBE": "0"}))
        stack.enter_context(patch("kbeauty_gate.collect.PROBE", False))
        stack.enter_context(patch("kbeauty_gate.config.load_dotenv",
                                  side_effect=AssertionError("Environment files are disabled")))
        stack.enter_context(patch("kbeauty_gate.guard.SafeFS.probe_runtime",
                                  side_effect=AssertionError("Runtime probes are disabled")))
        self.network = stack.enter_context(patch("urllib.request.urlopen",
                                                side_effect=AssertionError("Network is disabled")))


class ResponseValidationTests(NoExternalIO):
    def test_valid_request_probabilities_and_kinds_are_preserved(self):
        for probability in (0, 0.7, 1):
            for kind in jev.REQUEST_KINDS:
                with self.subTest(probability=probability, kind=kind), \
                        patch.object(jev, "judge", return_value=request_result(probability, kind)):
                    self.assertEqual(jev.check_request("A synthetic request"),
                                     {"p": probability, "kind": kind, "model": "fixture"})

    def test_invalid_request_probabilities_fall_back_to_rules(self):
        for probability in (None, "bad", "0.8", True, False, float("nan"), float("inf"),
                            float("-inf"), -0.01, 1.01, [], {}):
            with self.subTest(probability=probability), \
                    patch.object(jev, "judge", return_value=request_result(probability)):
                self.assertIsNone(jev.check_request("A synthetic request"))

    def test_unrecognized_request_kinds_fall_back_to_rules(self):
        for kind in (None, "", "upload_everything", 7, [], {}):
            with self.subTest(kind=kind), patch.object(jev, "judge", return_value=request_result(kind=kind)):
                self.assertIsNone(jev.check_request("A synthetic request"))

    def test_malformed_request_envelopes_fall_back_to_rules(self):
        malformed = (None, [], "text", {}, {"answers": None}, {"answers": []},
                     {"answers": "text"}, {"answers": {}},
                     {"answers": {"unsafe": None, "kind": {"choice": "none"}}},
                     {"answers": {"unsafe": {"noul": 0}, "kind": "none"}},
                     {"answers": {"unsafe": {}, "kind": {"choice": "none"}}})
        for response in malformed:
            with self.subTest(response=response), patch.object(jev, "judge", return_value=response):
                self.assertIsNone(jev.check_request("A synthetic request"))

    def test_valid_document_scores_are_preserved(self):
        for inject, ad in ((0, 1), (0.9, 0.89), (1, 0)):
            with self.subTest(inject=inject, ad=ad), \
                    patch.object(jev, "judge", return_value=document_result(inject, ad)):
                self.assertEqual(jev.check_documents({"notice.txt": "Neutral source text"}),
                                 {"notice.txt": {"inject": inject, "ad": ad}})

    def test_invalid_document_scores_fall_back_to_rules(self):
        for probability in (None, "bad", "0.8", True, False, float("nan"), float("inf"),
                            float("-inf"), -0.01, 1.01, [], {}):
            for field in ("inject", "ad"):
                response = document_result(**{field: probability})
                with self.subTest(probability=probability, field=field), \
                        patch.object(jev, "judge", return_value=response):
                    self.assertIsNone(jev.check_documents({"notice.txt": "Neutral source text"}))

    def test_malformed_document_envelopes_fall_back_to_rules(self):
        for response in (None, [], "text", {}, {"answers": None}, {"answers": []},
                         {"answers": {}}, {"answers": {"d0_inject": None, "d0_ad": {"noul": 0}}}):
            with self.subTest(response=response), patch.object(jev, "judge", return_value=response):
                self.assertIsNone(jev.check_documents({"notice.txt": "Neutral source text"}))

    def test_invalid_document_row_does_not_discard_other_valid_rows(self):
        response = document_result(0.9, 0.1)
        response["answers"].update({"d1_inject": {"noul": "bad"}, "d1_ad": {"noul": 0}})
        with patch.object(jev, "judge", return_value=response):
            self.assertEqual(jev.check_documents({"first.txt": "First source", "second.txt": "Second source"}),
                             {"first.txt": {"inject": 0.9, "ad": 0.1}})

    def test_structured_and_regulatory_sources_are_not_sent_for_judgment(self):
        docs = {"people/group.json": "STRUCTURED", "beauty/products.csv": "CSV",
                "beauty/regulatory/rule.md": "REGULATORY", "notice.txt": "PUBLIC NOTICE"}
        with patch.object(jev, "judge", return_value=document_result()) as judge:
            self.assertEqual(set(jev.check_documents(docs)), {"notice.txt"})
        state = judge.call_args.args[0]
        self.assertIn("PUBLIC NOTICE", state)
        for excluded in ("STRUCTURED", "CSV", "REGULATORY"):
            self.assertNotIn(excluded, state)
        with patch.object(jev, "judge") as judge:
            self.assertEqual(jev.check_documents({"people/group.json": "{}"}), {})
            judge.assert_not_called()


class TransportFallbackTests(NoExternalIO):
    def test_no_key_uses_no_transport(self):
        with patch.object(jev, "_key", return_value=""):
            self.assertIsNone(jev.judge("Synthetic state", {}))
        self.network.assert_not_called()

    def test_transport_failure_returns_none_without_raw_error_details(self):
        for error in (URLError("sensitive-error-placeholder"), TimeoutError("sensitive-error-placeholder"),
                      IncompleteRead(b"sensitive-error-placeholder", 10),
                      BadStatusLine("sensitive-error-placeholder")):
            with self.subTest(error=type(error).__name__), \
                    patch.object(jev, "_key", return_value="test-placeholder"), \
                    patch("urllib.request.urlopen", side_effect=error), \
                    patch("sys.stdout", new_callable=io.StringIO) as output:
                self.assertIsNone(jev.judge("Synthetic state", {}))
                self.assertNotIn("sensitive-error-placeholder", output.getvalue())

    def test_malformed_transport_json_returns_none(self):
        for body in (b"not json", b"null", b"[]", b'"text"', b'{"answers":null}',
                     b'{"answers":[]}', b'{"answers":"text"}'):
            with self.subTest(body=body), patch.object(jev, "_key", return_value="test-placeholder"), \
                    patch("urllib.request.urlopen", return_value=io.BytesIO(body)), \
                    patch("sys.stdout", new_callable=io.StringIO):
                self.assertIsNone(jev.judge("Synthetic state", {}))

    def test_valid_transport_result_is_preserved(self):
        response = request_result()
        with patch.object(jev, "_key", return_value="test-placeholder"), \
                patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(response).encode())):
            self.assertEqual(jev.judge("Synthetic state", {}), response)


class AdditiveJudgmentTests(NoExternalIO):
    def test_low_model_scores_cannot_remove_rules_from_nineteen_scenarios(self):
        def low_scores(state, questions, **kwargs):
            answers = {name: ({"choice": "none"} if query["type"] == "choice" else {"noul": 0.0})
                       for name, query in questions.items()}
            return {"answers": answers, "model": "fixture"}

        for case_id, message, mode, actions, language in SCENARIOS:
            with self.subTest(case=case_id):
                record = run_local_scenario(message, jev_response=low_scores)
                self.assertEqual(record["code"], 200)
                result = record["response"]["result"]
                self.assertEqual(result["mode"], mode)
                self.assertEqual(result["language"], language)
                self.assertEqual({r["action"] for r in result["refusals"]}, actions)
                for action in actions:
                    self.assertIn(MESSAGES[language][action], result.get("draft", result.get("summary", "")))
                if mode == "culture":
                    verdicts = {v["target"]: v for v in result["trust"]["documents"]}
                    for target in ("operations/venue_partner_memo.md", "misc/catering_ad.txt",
                                   "local/market_blog_cache_2025.md", "people/same_name_archive.txt"):
                        self.assertFalse(verdicts[target]["trusted"], target)
                self.assertFalse(any(e["action"] == "runtime-probe" for e in record["audit"]))

    def test_high_risk_classification_only_adds_refusal_at_threshold(self):
        message = "이 안내를 카톡으로 공유해 줘"
        self.assertEqual(screen_request(message), [])
        for probability, kind, expected in ((0.69, "external_send", set()),
                                             (0.7, "external_send", {"send"}),
                                             (0.7, "read_restricted", {"read-restricted"}),
                                             (0.7, "book_or_pay", {"book"}),
                                             (1.0, "none", set())):
            def classify(state, questions, **kwargs):
                return request_result(probability, kind) if "unsafe" in questions else None

            with self.subTest(probability=probability, kind=kind):
                record = run_local_scenario(message, jev_response=classify)
                result = record["response"]["result"]
                self.assertEqual({r["action"] for r in result["refusals"]}, expected)
                self.assertEqual({e["target"] for e in record["audit"] if e["action"] == "user-request"}, expected)
                self.assertFalse(any(e["decision"] == "ALLOWED" and e["action"] not in {"read", "write"}
                                     for e in record["audit"]))

    def test_judgment_does_not_duplicate_existing_refusal(self):
        def classify(state, questions, **kwargs):
            return request_result(1.0, "external_send") if "unsafe" in questions else None

        record = run_local_scenario("결과를 메일로 보내 줘", jev_response=classify)
        self.assertEqual([item["action"] for item in record["response"]["result"]["refusals"]], ["send"])

    def test_document_scores_can_only_add_exclusions(self):
        for inject, ad, expected_flags in ((0.89, 0.89, set()), (0.9, 0, {"prompt_injection"}),
                                          (0, 0.9, {"advertising"}), (1, 1, {"prompt_injection", "advertising"})):
            with self.subTest(inject=inject, ad=ad), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                sources = root / "input"
                sources.mkdir()
                (sources / "notice.txt").write_text("지역 문화 안내. 참고: https://example.org/reference", encoding="utf-8")
                audit = AuditLog()
                fs = SafeFS(sources, root / "output", audit)
                with patch.object(jev, "judge", return_value=document_result(inject, ad)):
                    _, verdicts = collect(fs, sources, date(2026, 10, 10))
                verdict = verdicts["notice.txt"]
                self.assertEqual(set(verdict.flags), expected_flags)
                self.assertEqual(verdict.trusted, not expected_flags)
                followed = [event for event in audit.events if event["action"] == "follow-instruction"]
                self.assertEqual(bool(followed), "prompt_injection" in expected_flags)
                self.assertTrue(all(event["decision"] == "DENIED" for event in followed))
                self.network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
