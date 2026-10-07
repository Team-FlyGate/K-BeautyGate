"""Culture date alignment using synthetic documents and mocked I/O only."""
from datetime import date
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from kbeauty_gate import agent, culture
from kbeauty_gate.config import Settings
from kbeauty_gate.trust import Verdict


SETTINGS = Settings("", "https://unused.invalid/chat", ["mock-model"],
                    "https://unused.invalid/embed", "mock-embed", 1)
GROUP = json.dumps({"date": "2026-10-10", "people": []})


def documents():
    docs = {
        "travel/visitor_group.json": GROUP,
        "local/mock_notice.txt": "2026-10-10 시장은 10:00–14:00 운영합니다. 북문을 이용합니다.",
        "travel/mock_route_card.md": "10/10 북문에서 성진정까지 도보 18분, 휠체어 우회 28분입니다.",
        "history/mock_note.md": "중수 연도는 1910년 또는 1919년으로 확인이 필요합니다.",
    }
    verdicts = {name: Verdict(name, True, 1.0, ["uncertain"] if name.startswith("history") else [])
                for name in docs if not name.endswith(".json")}
    return docs, verdicts


class CultureDateTests(unittest.TestCase):
    def test_single_explicit_date_uses_the_group_year_when_year_is_missing(self):
        for request in ("10월 11일에 가면 어떻게 돼?", "10월11일 문화 코스", "2026-10-11", "2026/10/11",
                        "10/11", "10-11", "2026年10月11日", "10月11日に行きます。", "10月11日去的话呢？",
                        "October 11", "Oct. 11, 2026", "11 October 2026"):
            with self.subTest(request=request):
                self.assertEqual(culture.culture_visit_date(request, "2026-10-10"), date(2026, 10, 11))
        self.assertEqual(culture.culture_visit_date("2027년 10월 11일", "2026-10-10"), date(2027, 10, 11))

    def test_unresolved_dates_keep_the_group_schedule(self):
        for request in ("성진정 해설만", "내일", "2월 30일", "10월 11일과 10월 12일", "1910년 또는 1919년 해설"):
            self.assertEqual(culture.culture_visit_date(request, "2026-10-10"), date(2026, 10, 10))

    @patch("kbeauty_gate.language.nvidia.chat", return_value=None)
    def test_changed_date_excludes_old_operations_and_requires_confirmation(self, chat):
        docs, verdicts = documents()
        result = culture.run_culture(docs, verdicts, "10월 11일에 가면 어떻게 돼?", SETTINGS, language="ko")
        self.assertEqual(result["visit_date"], "2026-10-11")
        self.assertTrue(result["notices"])
        self.assertIn("확인이 필요", result["localized"]["notices"][0])
        self.assertNotIn("10:00–14:00", " ".join(result["notices"]))
        facts = json.loads(chat.call_args.args[2])["facts"]
        self.assertEqual(facts["visit_date"], "2026-10-11")
        evidence = " ".join(facts["trusted_sources"].values())
        self.assertNotIn("10:00–14:00", evidence)
        self.assertNotIn("18분", evidence)
        self.assertIn("1910년 또는 1919년", evidence)

    @patch("kbeauty_gate.language.nvidia.chat", return_value=None)
    def test_notice_must_match_the_actual_requested_date_and_year(self, chat):
        docs, verdicts = documents()
        docs["local/new_notice.txt"] = "10월11일 시장은 09:00–12:00 운영합니다."
        docs["local/old_year_notice.txt"] = "2025-10-11 시장은 08:00에 문을 닫습니다."
        for name in ("local/new_notice.txt", "local/old_year_notice.txt"):
            verdicts[name] = Verdict(name, True, 1.0)
        result = culture.run_culture(docs, verdicts, "October 11", SETTINGS, language="ko")
        notices = " ".join(result["notices"])
        self.assertIn("09:00–12:00", notices)
        self.assertNotIn("10:00–14:00", notices)
        self.assertNotIn("08:00", notices)

    def test_collection_and_culture_share_the_date_without_beauty_profile_leakage(self):
        docs, verdicts = documents()
        with patch("kbeauty_gate.agent.get_settings", return_value=SETTINGS), \
                patch("kbeauty_gate.agent.AuditLog") as audit, \
                patch("kbeauty_gate.agent.SafeFS") as safe_fs, \
                patch("kbeauty_gate.agent.collect", return_value=(docs, verdicts)) as collect, \
                patch("kbeauty_gate.agent.suggest", return_value=[]), \
                patch("kbeauty_gate.language.nvidia.chat", return_value=None):
            safe_fs.return_value.read_text.return_value = GROUP
            safe_fs.return_value.saved = []
            audit.return_value.events = []
            for request, expected in (("10월 11일에 가면?", date(2026, 10, 11)),
                                      ("성진정 해설만 써 줘", date(2026, 10, 10))):
                with self.subTest(request=request):
                    result = agent.run(Path("/virtual/input"), Path("/virtual/output"),
                                       {"language": "ko", "visit_date": "2026-10-07", "skin_type": "dry"}, request, "culture")
                    self.assertEqual(collect.call_args.args[2], expected)
                    self.assertEqual(result["visit_date"], expected.isoformat())


if __name__ == "__main__":
    unittest.main()
