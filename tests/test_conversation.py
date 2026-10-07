"""Request routing with synthetic profiles and no model or filesystem I/O."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from kbeauty_gate import agent, conversation
from kbeauty_gate.config import Settings


SETTINGS = Settings("", "https://unused.invalid/chat", ["mock-model"],
                    "https://unused.invalid/embed", "mock-embed", 1)
DEFAULTS = {"skin_type": "combination", "concerns": ["pores"], "language": "ko",
            "visit_date": "2026-10-07", "time_window": "13:00-19:00", "areas": ["명동"]}
COMMON_REQUESTS = [
    "Alex Chen이 시장에서 먹을 수 있는 음식만 정리해 줘",
    "성진정 해설만 써 줘. 확실한 것과 추정은 구분해서",
    "휠체어 이용자 기준으로 코스를 다시 짜 줘",
    "10월 11일에 가면 어떻게 돼?",
    "결과를 메일로 보내 줘",
    "restricted 자료도 참고해 줘",
    "I'm vegan with a peanut allergy. What can I eat at the market?",
    "何を食べられますか？", "轮椅可以通行吗？", "我可以吃哪些食物？",
    "안녕하세요", "Please help me.",
]
BEAUTY_REQUESTS = [
    "복합성 피부, 칙칙하고 모공 고민", "토너와 선크림을 추천해 줘", "립밤을 찾고 있어요",
    "I have dry skin and want makeup and sunscreen.", "Recommend a skincare serum.",
    "敏感肌で赤みと乾燥が気になります。香料とアルコールは避けたいです。明洞でコスメを探しています。",
    "请推荐适合敏感皮肤的护肤品。", "請推薦適合敏感皮膚的護膚品。",
]


class RequestRoutingTests(unittest.TestCase):
    @patch("kbeauty_gate.conversation.extract_profile", side_effect=AssertionError("Culture must not extract a beauty profile"))
    def test_new_requests_default_to_culture_despite_beauty_defaults(self, extract):
        defaults = json.loads(json.dumps(DEFAULTS))
        for message in COMMON_REQUESTS:
            with self.subTest(message=message):
                turn = conversation.build_turn(SETTINGS, message, None, DEFAULTS)
                self.assertEqual(turn["mode"], "culture")
                self.assertEqual(turn["profile"]["_mode"], "culture")
                self.assertNotIn("skin_type", turn["profile"])
                self.assertNotIn("visit_date", turn["profile"])
        self.assertEqual(DEFAULTS, defaults)
        extract.assert_not_called()

    @patch("kbeauty_gate.conversation.extract_profile", return_value={"skin_type": "sensitive"})
    def test_clear_beauty_requests_in_all_five_languages(self, extract):
        for message in BEAUTY_REQUESTS:
            with self.subTest(message=message):
                extract.reset_mock()
                turn = conversation.build_turn(SETTINGS, message, None, DEFAULTS)
                self.assertEqual(turn["mode"], "beauty")
                self.assertEqual(turn["profile"]["skin_type"], "sensitive")
                self.assertEqual(turn["profile"]["_mode"], "beauty")
                self.assertEqual(turn["profile"]["request"], message)
                extract.assert_called_once()

    @patch("kbeauty_gate.conversation.extract_profile", return_value={})
    def test_short_followups_keep_beauty_context_or_a_saved_skin_profile(self, extract):
        for state in ({"_mode": "beauty"}, {"skin_type": "dry"}):
            for message in ("예산 줄여 줘", "50000", "명동", "10월 11일에 가면?", "Please make it cheaper.",
                            "予算を下げてください。", "预算改为4万韩元。", "請用繁體中文回答。",
                            "향료 빼 줘", "avoid alcohol", "香料なしで", "不要酒精"):
                with self.subTest(state=state, message=message):
                    turn = conversation.build_turn(SETTINGS, message, state, DEFAULTS)
                    self.assertEqual(turn["mode"], "beauty")
        self.assertEqual(conversation.select_mode("예산 줄여 줘"), "culture")
        self.assertEqual(conversation.select_mode("향료 빼 줘"), "culture")

    @patch("kbeauty_gate.conversation.extract_profile", side_effect=AssertionError("A clear common task must bypass beauty extraction"))
    def test_common_requests_override_beauty_context(self, extract):
        state = {"_mode": "beauty", "skin_type": "dry", "language": "en"}
        for message in ("피부 추천 대신 성진정 해설만 써 줘", "휠체어면?", "다른 비건 음식은?", "음식의 알코올 성분을 빼 줘",
                        "Please plan a cultural itinerary.", "文化コースを案内してください。",
                        "请介绍古市场的历史。", "請介紹古市場的歷史。"):
            with self.subTest(message=message):
                turn = conversation.build_turn(SETTINGS, message, state, DEFAULTS)
                self.assertEqual(turn["mode"], "culture")
                self.assertEqual(turn["profile"]["_mode"], "culture")
        self.assertEqual(state["_mode"], "beauty")
        extract.assert_not_called()

    def test_shopping_area_does_not_override_an_explicit_food_request(self):
        for area in ("명동", "성수", "홍대"):
            with self.subTest(area=area):
                self.assertEqual(conversation.select_mode(area), "beauty")
                self.assertEqual(conversation.select_mode(f"{area}에서 비건 음식을 먹고 싶어요"), "culture")
                self.assertEqual(conversation.select_mode(f"{area}에서 비건 화장품을 찾고 있어요"), "beauty")
                for food in ("점심 먹고 싶어요", "저녁 식당 알려줘", "맛집 찾아 줘", "밥 먹기 좋은 곳", "아침 추천"):
                    self.assertEqual(conversation.select_mode(f"{area}에서 {food}"), "culture")

    @patch("kbeauty_gate.conversation.extract_profile", return_value={})
    def test_culture_context_ignores_stale_skin_but_can_switch_back_to_beauty(self, extract):
        state = {"_mode": "culture", "skin_type": "dry", "language": "ja"}
        turn = conversation.build_turn(SETTINGS, "更短一些", state, DEFAULTS)
        self.assertEqual(turn["mode"], "culture")
        extract.assert_not_called()
        turn = conversation.build_turn(SETTINGS, "請推薦防曬產品。", turn["profile"], DEFAULTS)
        self.assertEqual(turn["mode"], "beauty")
        extract.assert_called_once()

    def test_ambiguous_text_and_similar_words_do_not_become_beauty(self):
        for message in ("독립운동 해설", "Do you have napkins?", "성분을 알려 주세요", "Please help me with an unrelated task."):
            self.assertEqual(conversation.select_mode(message), "culture")
        self.assertEqual(conversation.select_mode("새로운 프로젝트 계획을 작성해 줘", {"_mode": "beauty"}), "culture")
        self.assertIs(agent.BEAUTY_WORDS, conversation.BEAUTY_WORDS)

    def test_agent_auto_uses_the_same_routing_as_conversation(self):
        with patch("kbeauty_gate.agent.get_settings", return_value=SETTINGS), \
                patch("kbeauty_gate.agent.AuditLog") as audit, \
                patch("kbeauty_gate.agent.SafeFS") as safe_fs, \
                patch("kbeauty_gate.agent.collect", return_value=({}, {})), \
                patch("kbeauty_gate.agent.run_culture", side_effect=lambda *args, **kwargs: {"people": [], "localized": {"draft": "Draft"}}) as cultural, \
                patch("kbeauty_gate.agent.render_culture", return_value="Draft"), \
                patch("kbeauty_gate.agent.suggest", return_value=[]), \
                patch("kbeauty_gate.agent.run_beauty", return_value={"mode": "beauty"}) as beauty, \
                patch("kbeauty_gate.nvidia.chat", side_effect=AssertionError("No model calls")):
            safe_fs.return_value.read_text.return_value = '{"date":"2026-10-10"}'
            safe_fs.return_value.saved = []
            audit.return_value.events = []
            cases = [(message, {}) for message in COMMON_REQUESTS + BEAUTY_REQUESTS]
            cases += [("예산 줄여 줘", {"_mode": "beauty", "skin_type": "dry"}),
                      ("성진정 해설만", {"_mode": "beauty", "skin_type": "dry"}),
                      ("Please make it shorter.", {"_mode": "culture", "skin_type": "dry"})]
            for message, profile in cases:
                with self.subTest(message=message, profile=profile):
                    cultural.reset_mock()
                    beauty.reset_mock()
                    expected = conversation.select_mode(message, profile)
                    result = agent.run(Path("/virtual/input"), Path("/virtual/output"), profile, message, "auto")
                    self.assertEqual(result["mode"], expected)
                    self.assertEqual(cultural.call_count, int(expected == "culture"))
                    self.assertEqual(beauty.call_count, int(expected == "beauty"))


if __name__ == "__main__":
    unittest.main()
