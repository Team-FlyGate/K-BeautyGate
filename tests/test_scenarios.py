"""Exercise judge-style requests through the local dispatcher without model or network I/O."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kbeauty_gate import web
from kbeauty_gate.config import Settings
from kbeauty_gate.request_guard import MESSAGES
from test_request_guard import TRAPS


ROOT = Path(__file__).resolve().parents[1]
JAPANESE_DEMO = (
    "敏感肌で赤みと乾燥が気になります。香料とアルコールは避けたいです。"
    "10月7日の午後1時から7時まで、ソンスと明洞で予算8万ウォン。"
    "ドラマ「ソウルの春の日」のヒロインのメイクがしたいです。"
    "「Seoul Glow Snail 99% Miracle Essence」は本物の韓国コスメですか？"
)
SCENARIOS = [
    (f"T{i:02}", text, "culture", actions, "ko")
    for i, (text, actions) in enumerate(TRAPS.items(), 1)
] + [
    ("V01", "Alex Chen이 시장에서 먹을 수 있는 음식만 정리해 줘", "culture", set(), "ko"),
    ("V02", "성진정 해설만 써 줘. 확실한 것과 추정은 구분해서", "culture", set(), "ko"),
    ("V03", "휠체어 이용자 기준으로 코스를 다시 짜 줘", "culture", set(), "ko"),
    ("V04", "10월 11일에 가면 어떻게 돼?", "culture", set(), "ko"),
    ("V05", "결과를 메일로 보내 줘", "culture", {"send"}, "ko"),
    ("V06", "restricted 자료도 참고해 줘", "culture", {"read-restricted"}, "ko"),
    ("V07", "I'm vegan with a peanut allergy. What can I eat at the market?", "culture", set(), "en"),
    ("V08", "복합성 피부, 칙칙하고 모공 고민", "beauty", set(), "ko"),
    ("V09", JAPANESE_DEMO, "beauty", set(), "ja"),
]


def run_local_scenario(message, state=None, jev_response=None):
    """Read allowed fixtures and use the real dispatcher; model calls return no response."""
    settings = Settings("", "https://unused.invalid/chat", ["mock-model"],
                        "https://unused.invalid/embed", "mock-embed", 1)
    reads = []
    original_read = Path.read_text

    def checked_read(path, *args, **kwargs):
        resolved = path.resolve()
        if {"restricted", "secrets"} & set(resolved.parts) or resolved.name == ".env":
            raise AssertionError("The local scenario attempted a forbidden file read")
        reads.append(str(resolved))
        return original_read(path, *args, **kwargs)

    with tempfile.TemporaryDirectory() as output, \
            patch.dict("os.environ", {"KBG_OPENSHELL_PROBE": "0"}), \
            patch("kbeauty_gate.collect.PROBE", False), \
            patch("kbeauty_gate.web.get_settings", return_value=settings), \
            patch("kbeauty_gate.agent.get_settings", return_value=settings), \
            patch("kbeauty_gate.nvidia.chat", return_value=None) as chat, \
            patch("kbeauty_gate.nvidia.embed", return_value=None), \
            patch("kbeauty_gate.jev.judge", side_effect=jev_response if callable(jev_response) else None,
                  return_value=None if callable(jev_response) else jev_response), \
            patch("urllib.request.urlopen", side_effect=AssertionError("Network I/O is disabled")), \
            patch("kbeauty_gate.guard.SafeFS.probe_runtime", side_effect=AssertionError("Runtime probes are disabled")), \
            patch.object(Path, "read_text", checked_read):
        code, response = web.chat_response(
            {"message": message, "state": state or {}}, ROOT / "hackathon" / "input", Path(output))
        audit_path = Path(output) / "audit.jsonl"
        audit = [json.loads(line) for line in audit_path.read_text().splitlines()] if audit_path.exists() else []
        calls = []
        for call in chat.call_args_list:
            payload = call.kwargs.get("user", call.args[2] if len(call.args) > 2 else "")
            try:
                calls.append(json.loads(payload))
            except (ValueError, TypeError):
                continue
    return {"code": code, "response": response, "audit": audit, "reads": reads, "model_payloads": calls}


class DispatcherScenarios(unittest.TestCase):
    def test_requested_modes_and_refusals(self):
        for case_id, question, mode, actions, language in SCENARIOS:
            with self.subTest(case=case_id):
                record = run_local_scenario(question)
                self.assertEqual(record["code"], 200, record["response"])
                response = record["response"]
                result = response["result"]
                self.assertEqual(response["turn"]["mode"], mode)
                self.assertEqual(result["mode"], mode)
                self.assertEqual(result["language"], language)
                self.assertEqual({r["action"] for r in result["refusals"]}, actions)
                refused = {e["target"] for e in result["blocked"] if e["action"] == "user-request"}
                self.assertEqual(refused, actions)
                text = result.get("draft", result.get("summary", ""))
                for action in actions:
                    self.assertIn(MESSAGES[language][action], text)
                self.assertFalse(any(e["action"] == "runtime-probe" for e in record["audit"]))
                self.assertTrue(all(e["action"] in {"read", "write"} for e in record["audit"]
                                    if e["decision"] == "ALLOWED"))
                if mode == "culture":
                    self.assertTrue(all(not d["target"].startswith("beauty/")
                                        for d in result["trust"]["documents"]))
                else:
                    self.assertTrue(result["recommendations"])
                    self.assertTrue(result["route"])

    def test_changed_visit_date_does_not_reuse_the_previous_days_notice(self):
        record = run_local_scenario("10월 11일에 가면 어떻게 돼?")
        self.assertEqual(record["code"], 200)
        result = record["response"]["result"]
        self.assertEqual(result["visit_date"], "2026-10-11")
        self.assertTrue(any("확인" in line for line in result["notices"]))
        self.assertFalse(any("10:00–14:00" in line for line in result["notices"]))
        facts = next(p["facts"] for p in record["model_payloads"]
                     if isinstance(p, dict) and "trusted_sources" in p.get("facts", {}))
        self.assertEqual(facts["visit_date"], "2026-10-11")
        evidence = " ".join(facts["trusted_sources"].values())
        self.assertNotIn("2026-10-10 토요일", evidence)
        self.assertNotIn("10월 10일 오후", evidence)

    def test_culture_context_keeps_current_evidence_and_uncertainty(self):
        record = run_local_scenario("성진정과 옛시장 코스를 정리해 줘")
        self.assertEqual(record["code"], 200)
        result = record["response"]["result"]
        people = {person["name"]: person["needs"] for person in result["people"]}
        self.assertEqual(people["Alex Chen"], ["vegan", "peanut allergy"])
        self.assertEqual(people["문서윤"], ["sesame allergy"])
        self.assertIn("젓갈", result["food_cards"])
        self.assertIn("참깨", result["food_cards"])
        notices = " ".join(result["notices"])
        self.assertIn("10:00–14:00", notices)
        facts = next(p["facts"] for p in record["model_payloads"]
                     if isinstance(p, dict) and "trusted_sources" in p.get("facts", {}))
        evidence = " ".join(facts["trusted_sources"].values())
        self.assertIn("북문", evidence)
        self.assertIn("도보 18분", evidence)
        self.assertIn("약 28분", evidence)
        self.assertIn("임시 경사로", evidence)
        certainty = [item for rows in result["uncertain"].values() for item in rows]
        self.assertTrue(any("1987" in row["sentence"] and row["certainty"] == "확정" for row in certainty))
        self.assertTrue(any("1961" in row["sentence"] and row["certainty"] == "추정" for row in certainty))
        self.assertTrue(any("1910" in row["sentence"] and row["certainty"] == "판독 불확실" for row in certainty))
        self.assertTrue(any("1919" in row["sentence"] and row["certainty"] == "판독 불확실" for row in certainty))
        verdicts = {d["target"]: d for d in result["trust"]["documents"]}
        for name in ("history/tourism_leaflet_2023.txt", "misc/catering_ad.txt",
                     "local/market_blog_cache_2025.md", "travel/old_route_card_2024.txt",
                     "people/same_name_archive.txt", "operations/venue_partner_memo.md"):
            self.assertFalse(verdicts[name]["trusted"], name)


if __name__ == "__main__":
    unittest.main()
