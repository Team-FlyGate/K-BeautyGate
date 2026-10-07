import unittest

from kbeauty_gate.fact_guard import check_text

# 실측(astra_scenario_checks_1430.md)에서 모델이 실제로 만든 잘못된 문장과, 통과해야 하는 정상 문장
CASES = [
    ("2026-10-10 토요일 남문에서 해안 데크까지 도보 12분 경로를 이용합니다.", "ko", "old_route"),
    ("성진정은 수백 년 전 원형 그대로 보존된 정자이다.", "ko", "original_form"),
    ("참깨 알레르기가 없는 Alex Chen은 들깨 사용 음식을 고려할 수 있으나 확인이 필요합니다.", "ko", "no_allergy"),
    ("12:40 - 13:00 - 성진정에서 북문까지 우회로 복귀 (약 28분)", "ko", "timetable"),
    ("문서윤: 들깨와 참깨 구분 확인 필요 (들깨는 안전, 참깨는 위험)", "ko", "food_safety"),
    ("Alex Chen (vegan, peanut allergy) can eat plain steamed rice and fruit. Ask vendors.", "en", "food_safety"),
]
CLEAN = [
    ("'원형 그대로'라는 표현은 근거 확인 전까지 쓰지 않아요.", "ko"),
    ("'2023 관광 홍보 전단'의 원형 보존 주장은 현장 조사 메모와 충돌해 제외했습니다.", "ko"),
    ("알레르기 확인 후 채식 가능한 간식 구매 (참기름·들기름 사용 여부 상인에게 필수 확인)", "ko"),
    ("오전 10시 해담 옛시장 북문 입장 → 도보 18분 → 성진정", "ko"),
    ("No dish can be called safe without checking the ingredients.", "en"),
    ("12:30 - 13:00 - 휠체어 우회로로 이동 (약 28분)", "ko"),
]


class FactGuardTests(unittest.TestCase):
    def test_known_failures_are_removed_and_corrected(self):
        for text, lang, rule in CASES:
            fixed, hits = check_text(text, lang)
            self.assertEqual([h["rule"] for h in hits], [rule], text)
            self.assertNotIn(text.strip(), fixed)
            self.assertIn("\n- ", "\n" + fixed, "정정 문장이 붙어야 함")

    def test_correct_sentences_pass_unchanged(self):
        for text, lang in CLEAN:
            fixed, hits = check_text(text, lang)
            self.assertEqual(hits, [], text)
            self.assertEqual(fixed, text)

    def test_corrections_follow_user_language(self):
        fixed, _ = check_text("成津亭は原形のまま保存された東屋です。", "ja")
        self.assertIn("1987", fixed)
        self.assertNotRegex(fixed, "[가-힣]")


if __name__ == "__main__":
    unittest.main()
