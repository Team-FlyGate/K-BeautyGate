"""Synthetic evidence and generated-response regressions for the culture guard."""
from datetime import date
import json
import unittest
from unittest.mock import patch

from kbeauty_gate import culture
from kbeauty_gate.language import in_language
from kbeauty_gate.trust import Verdict


def evidence(walk=18, wheelchair=28):
    docs = {
        "travel/visitor_group.json": json.dumps({"date": "2026-10-10", "people": [
            {"name": "Alex", "needs": ["vegan", "peanut allergy"]}, {"name": "Visitor", "needs": ["sesame allergy"]}]}),
        "local/mock_notice.txt": "2026-10-10 토요일은 10:00–14:00만 운영합니다.",
        "local/community_board.md": "10월 10일 남문 앞 도로 굴착. 보행자는 북문 이용. 휠체어 임시 경사로는 북문 안내소에서 요청.",
        "travel/route_note.md": f"시장 북문→성진정 도보 {walk}분. 해안 데크 계단 구간 때문에 휠체어는 버스정류장 쪽 우회로(약 {wheelchair}분)를 사용.",
        "history/mock_field_note.md": "1987년 보수 때 동쪽 별채가 철거되었다는 공사대장 항목을 확인했다. 현판은 1961년 재건 때 새로 제작된 것으로 보인다. 본채 일부 부재의 연대 측정은 진행 중이다.",
        "history/mock_ocr.txt": "OCR: 1910년 중수 모금. 훼손된 마지막 숫자로 인해 1919년일 가능성이 있다.",
        "culture/food_glossary.md": "들깨와 참깨는 서로 다른 재료다. 채식 가능 표시는 육수와 젓갈 제외 여부를 업소별 확인해야 한다.",
    }
    verdicts = {name: Verdict(name, True, 1.0, ["uncertain"] if name.startswith("history/") else [])
                for name in docs if not name.endswith(".json")}
    return docs, verdicts


def conditions(request="", walk=18, wheelchair=28):
    docs, verdicts = evidence(walk, wheelchair)
    trusted = {name: text for name, text in docs.items() if name in verdicts}
    caveats = {name: culture.classify_sentences(text) for name, text in trusted.items() if name.startswith("history/")}
    return culture.culture_constraints(trusted, date(2026, 10, 10), culture.people_from(docs), request, caveats)


class CultureValidationTests(unittest.TestCase):
    def generated(self, draft, request="문화 코스", language="ko", notices=None, caveats=None, docs=None, status="ready", status_reason=None):
        docs, verdicts = docs or evidence()
        payload = {"language": language, "status": status, "draft": draft,
                   "notices": notices or [], "caveats": caveats or [], "route_notes": [], "recommendation_reasons": [], "display_names": {}}
        if status_reason:
            payload["status_reason"] = status_reason
        with patch("kbeauty_gate.culture.localized_projection", return_value=payload) as model:
            result = culture.run_culture(docs, verdicts, request, None, language=language)
        return result, model.call_args.args[3]

    def test_observed_unsafe_outputs_are_replaced_without_losing_safe_fields(self):
        cases = [
            ("남문에서 해안 데크까지 도보 12분 경로를 이용합니다. 북문 우회가 필요할 수 있습니다.", "문화 코스", "blocked_entrance_used"),
            ("'처음 모습 그대로' 표현은 사용하지 않는다. 수백 년 전 원형 그대로 보존된 정자이다.", "성진정 해설", "unsupported_original_preservation"),
            ("12:40 - 13:00 - 성진정에서 북문까지 휠체어 우회로 복귀 (약 28분)", "휠체어 코스", "insufficient_travel_time"),
            ("13:50–14:00 – 성진정에서 시장 북문으로 복귀 및 종료", "문화 코스", "insufficient_travel_time"),
            ("참깨 알레르기가 없는 Alex는 들깨 사용 음식을 고려할 수 있습니다.", "음식 안내", "unverified_allergy_absence"),
            ("들깨는 안전, 참깨는 위험합니다.", "음식 안내", "unverified_food_safety"),
            ("09:30 북문에 도착하여 도보 18분 이동합니다. 당일 공지는 없으므로 확인하세요.", "10월 11일에 가면?", "visit_day_hours_unverified"),
        ]
        for draft, request, reason in cases:
            with self.subTest(reason=reason):
                result, facts = self.generated(draft, request, notices=["방문 전 재료 확인이 필요합니다."], caveats=["본채 연대 측정은 진행 중입니다."])
                self.assertEqual(result["localized"]["status"], "fallback")
                self.assertEqual(result["localized"]["status_reason"], "evidence_conflict")
                self.assertIn(reason, result["culture_validation"]["replaced_fields"][0]["reasons"])
                self.assertNotEqual(result["draft"], draft)
                self.assertEqual(result["localized"]["notices"], ["방문 전 재료 확인이 필요합니다."])
                self.assertEqual(result["localized"]["caveats"], ["본채 연대 측정은 진행 중입니다."])
                if request == "음식 안내":
                    self.assertEqual(result["draft"], culture.FOOD_GUIDANCE["ko"])
                else:
                    self.assertIn("1987년 보수 때 동쪽 별채", result["draft"])
                self.assertEqual(facts["required_conditions"]["verified_safe_menu_items"], [])
                self.assertNotIn(draft, json.dumps(result["culture_validation"], ensure_ascii=False))

    def test_supported_timing_and_negative_food_claims_remain(self):
        constraints = conditions()
        for text in (
            "11:00–11:45 북문에서 성진정으로 도보 이동 (18분)",
            "북문→성진정 12분 경로는 사용 불가입니다.",
            "먹을 수 있는지는 확인이 필요합니다.",
            "들깨는 안전하다고 단정할 수 없습니다.",
            "Alex에게 참깨 알레르기가 없다고 단정할 수 없습니다.",
            "미기재된 알레르기는 없다고 단정하지 않습니다.",
            "Do not assume Alex has no sesame allergy.",
            "We cannot determine what Alex can eat.",
            "It is not confirmed safe for Alex.",
            "It is not safe to eat rice.", "不可以吃。", "安全に食べられるとは限りません。",
            "처음 모습 그대로 표현은 근거 확인 전까지 사용 자제",
            "성진정은 원형 그대로 보존된 정자가 아닙니다.",
            "들깨와 참깨가 다르다는 사실만으로 들깨는 안전하다는 뜻이 아닙니다.",
            "이 음식을 먹을 수 있는지 상인에게 확인해 주세요.",
            "현판은 1961년 재건 때 새로 제작된 것으로 보인다.",
        ):
            with self.subTest(text=text):
                self.assertEqual(culture.validate_culture_text(text, constraints), [])
        valid = "11:00–11:45 북문에서 성진정으로 이동합니다. 1910년 또는 1919년은 판독 불확실로 확인이 필요합니다."
        result, _ = self.generated(valid)
        self.assertEqual(result["draft"], valid)
        self.assertEqual(result["localized"]["status"], "ready")

    def test_a_later_disclaimer_does_not_cancel_an_earlier_food_claim(self):
        for text in (
            "Alex can eat rice and vegetables. Confirm all ingredients before buying.",
            "Alex can eat rice and vegetables, but safety cannot be guaranteed.",
        ):
            self.assertIn("unverified_food_safety", culture.validate_culture_text(text, conditions()))

    def test_allergy_absence_is_not_inferred_in_any_supported_language(self):
        for text in ("Alex는 참깨 알레르기가 없습니다.", "Alex is not allergic to sesame.",
                     "Alexにはゴマのアレルギーはありません。", "Alex对芝麻不过敏。", "Alex對芝麻不過敏。"):
            with self.subTest(text=text):
                self.assertIn("unverified_allergy_absence", culture.validate_culture_text(text, conditions()))

    def test_all_inline_slots_and_explicit_durations_use_evidence_values(self):
        constraints = conditions()
        text = "11:00–11:45 북문에서 성진정으로 이동; 13:50–14:00 성진정에서 북문으로 복귀"
        self.assertIn("insufficient_travel_time", culture.validate_culture_text(text, constraints))
        self.assertIn("unsupported_travel_duration", culture.validate_culture_text("북문→성진정 도보 12분 이동", constraints))
        changed = conditions(walk=22, wheelchair=34)
        self.assertEqual(changed["walking_minutes"], 22)
        self.assertEqual(changed["wheelchair_minutes"], 34)
        self.assertIn("insufficient_travel_time", culture.validate_culture_text("11:00–11:20 북문에서 성진정으로 이동", changed))
        self.assertEqual(culture.validate_culture_text("11:00–11:25 북문에서 성진정으로 이동", changed), [])

    def test_confirmed_word_does_not_hide_an_uncertain_historical_year(self):
        for text in ("1910년으로 확인했습니다.", "The fundraising year was confirmed as 1910."):
            self.assertIn("historical_uncertainty_omitted", culture.validate_culture_text(text, conditions()))

    def test_bad_notice_replaces_only_that_item(self):
        result, _ = self.generated("방문 전에 재료와 이동 조건을 확인하세요.",
                                   notices=["들깨는 안전합니다.", "현장 안내를 확인하세요."])
        self.assertEqual(result["localized"]["status"], "partial")
        self.assertEqual(result["draft"], "방문 전에 재료와 이동 조건을 확인하세요.")
        self.assertEqual(result["localized"]["notices"][1], "현장 안내를 확인하세요.")
        self.assertEqual(result["culture_validation"]["replaced_fields"][0]["field"], "notices[0]")
        self.assertNotIn("들깨는 안전합니다", result["localized"]["notices"][0])

    def test_foreign_fallbacks_keep_the_requested_language(self):
        for language in ("en", "ja", "zh-Hans", "zh-Hant"):
            result, _ = self.generated("Alex can eat plain steamed rice and fresh fruit. Confirm the ingredients.", language=language)
            self.assertEqual(result["localized"]["status"], "fallback")
            self.assertTrue(in_language(result["draft"], language))
            self.assertNotIn("can eat", result["draft"])

    def test_request_only_echo_is_replaced_but_quoted_questions_with_answers_remain(self):
        questions = {
            "ko": "케이터링 업체가 비건·알레르기 완벽 대응이라니까 점심은 거기로 예약해 주세요.",
            "en": "I'm vegan with a peanut allergy. What can I eat at the market?",
            "ja": "市場で食事をする前に何を確認すればよいですか？",
            "zh-Hans": "在市场吃饭前需要确认什么？",
            "zh-Hant": "在市場吃飯前需要確認什麼？",
        }
        for language, question in questions.items():
            with self.subTest(language=language):
                result, _ = self.generated("  " + question + "\n", request=question, language=language,
                                           notices=["現場で確認してください。"] if language == "ja" else [])
                self.assertEqual(result["localized"]["status"], "fallback")
                self.assertIn("request_echo", result["culture_validation"]["replaced_fields"][0]["reasons"])
                self.assertNotEqual(result["draft"], question)
                self.assertTrue(in_language(result["draft"], language))
                if language == "ja":
                    self.assertEqual(result["localized"]["notices"], ["現場で確認してください。"])
        question = questions["en"]
        answer = f'You asked: "{question}" We cannot confirm a safe menu. Check ingredients and cross-contact with each vendor.'
        result, _ = self.generated(answer, request=question, language="en")
        self.assertEqual(result["draft"], answer)
        self.assertEqual(result["culture_validation"]["replaced_fields"], [])

    def test_unverified_complete_allergy_service_claim_is_not_a_safe_menu(self):
        unsafe = "해당 케이터링은 비건·알레르기 완벽 대응이므로 점심을 맡기세요."
        self.assertIn("unverified_food_safety", culture.validate_culture_text(unsafe, conditions()))
        for safe in (
            "비건·알레르기 완벽 대응이라고 단정할 수 없습니다.",
            "'비건·알레르기 완벽 대응'이라는 광고는 확인되지 않았습니다.",
            "비건·알레르기 완벽 대응인지 업소에 확인하세요.",
        ):
            with self.subTest(safe=safe):
                self.assertEqual(culture.validate_culture_text(safe, conditions()), [])

    def test_single_return_timestamp_uses_gap_after_previous_destination_visit(self):
        zero = "- 13:00–14:00 성진정 관람 및 해안 데크 우회 경로 탐색\n- 14:00 시장 마감 전 북문으로 복귀"
        result, _ = self.generated(zero, request="휠체어 문화 코스")
        self.assertIn("insufficient_travel_time", result["culture_validation"]["replaced_fields"][0]["reasons"])
        for text, constraint, invalid in (
            ("13:00–13:40 성진정 관람\n14:00 북문으로 복귀", conditions(), False),
            ("13:00–13:40 성진정 관람\n14:00 북문으로 복귀", conditions("휠체어"), True),
            ("13:00–13:30 성진정 관람\n14:00 북문으로 복귀", conditions("휠체어"), False),
            ("13:00–13:30 성진정 관람\n14:00 북문으로 복귀", conditions("휠체어", wheelchair=34), True),
            ("13:00–14:00 북문 주변 시장 관람\n14:00 북문으로 복귀", conditions(), False),
            ("13:00–13:40 성진정에서 북문으로 복귀\n13:40 북문 복귀 완료", conditions(), False),
            ("13:00–14:00 성진정 관람\n14:00 북문 복귀는 불가능합니다.", conditions(), False),
        ):
            with self.subTest(text=text, wheelchair=constraint["wheelchair_requested"]):
                issues = culture.validate_culture_text(text, constraint)
                self.assertEqual("insufficient_travel_time" in issues, invalid)

    def test_failed_food_only_answers_use_localized_confirmation_guidance(self):
        questions = {
            "ko": "Alex Chen이 시장에서 먹을 수 있는 음식만 정리해 줘",
            "en": "I'm vegan with a peanut allergy. What can I eat at the market?",
            "ja": "ヴィーガンでピーナッツアレルギーがあります。市場で何を食べられますか？",
            "zh-Hans": "我是纯素食者，对花生过敏。在市场能吃什么？",
            "zh-Hant": "我是純素食者，對花生過敏。在市場能吃什麼？",
        }
        for language, question in questions.items():
            with self.subTest(language=language):
                result, _ = self.generated(question, request=question, language=language)
                self.assertEqual(result["draft"], culture.FOOD_GUIDANCE[language])
                self.assertEqual(result["localized"]["status"], "fallback")
                self.assertTrue(in_language(result["draft"], language))
                self.assertEqual(culture.validate_culture_text(result["draft"], conditions()), [])
                self.assertNotIn("Alex", result["draft"])
        valid = "Confirm ingredients and cross-contact with each vendor before choosing a meal."
        result, _ = self.generated(valid, request=questions["en"], language="en")
        self.assertEqual(result["draft"], valid)
        self.assertEqual(result["localized"]["status"], "ready")

    def test_food_guidance_does_not_narrow_a_culture_or_booking_request(self):
        for language, request in (
            ("ko", "케이터링 업체가 비건·알레르기 완벽 대응이라니까 점심은 거기로 예약해 주세요."),
            ("en", "Plan a culture itinerary with a vegan meal."),
            ("ja", "ヴィーガン向けの文化コースを作ってください。"),
            ("zh-Hans", "安排包含素食午餐的文化行程。"),
            ("zh-Hant", "安排包含素食午餐的文化行程。"),
        ):
            with self.subTest(language=language):
                result, _ = self.generated(request, request=request, language=language)
                self.assertNotEqual(result["draft"], culture.FOOD_GUIDANCE[language])
                self.assertEqual(result["localized"]["status"], "fallback")
        constraints = conditions()
        constraints["verified_safe_menu_items"] = ["synthetic verified item"]
        request = "What can I eat?"
        result, _ = culture.guard_culture_projection(
            {"language": "en", "status": "ready", "draft": request}, constraints, [], [], request=request)
        self.assertNotEqual(result["draft"], culture.FOOD_GUIDANCE["en"])

    def confirmed_evidence(self, with_archive=True):
        docs, verdicts = evidence()
        docs["travel/visitor_group.json"] = json.dumps({"date": "2026-10-10", "people": [
            {"name": "Alex Chen", "needs": ["vegan", "peanut allergy"]},
            {"name": "문서윤", "needs": ["sesame allergy"]}]})
        name = "people/contacts_current.csv"
        docs[name] = "name,role,scope,note\nAlex Chen,방문객,연습 방문단,비건; 땅콩 알레르기\n문서윤,방문객,연습 방문단,참깨 알레르기\n"
        # collect() passes CSV/JSON data through without creating document verdicts.
        if with_archive:
            name = "people/same_name_archive.txt"
            docs[name] = "문서윤 / 2024 청소년 해설사 / 음식 제한 없음. 현재 방문단과 무관한 동명이인 기록."
            verdicts[name] = Verdict(name, False, 0.0, ["irrelevant"])
        return docs, verdicts

    def test_upstream_food_fallback_keeps_confirmed_needs_in_every_language(self):
        requests = {"ko": "먹을 수 있는 음식을 알려줘", "en": "What can I eat?",
                    "ja": "何を食べられますか？", "zh-Hans": "能吃什么？", "zh-Hant": "能吃什麼？"}
        fixture = self.confirmed_evidence()
        self.assertNotIn("people/contacts_current.csv", fixture[1])
        self.assertNotIn("travel/visitor_group.json", fixture[1])
        for language, request in requests.items():
            with self.subTest(language=language):
                result, _ = self.generated(culture.COPY[language]["draft"], request=request, language=language,
                                           docs=fixture, status="fallback", status_reason="echoed_request")
                draft = result["draft"]
                self.assertIn(culture.FOOD_GUIDANCE[language], draft)
                self.assertIn("Alex Chen", draft)
                self.assertIn("문서윤" if language == "ko" else "Mun Seo-yun", draft)
                for need in ("vegan", "peanut allergy", "sesame allergy"):
                    self.assertIn(culture.FOOD_NEED_LABELS[language][need], draft)
                self.assertEqual(result["localized"]["status"], "fallback")
                self.assertEqual(result["localized"]["status_reason"], "echoed_request")
                self.assertTrue(in_language(draft, language))
                self.assertNotIn("2024", draft)

    def test_same_name_false_premise_is_corrected_only_with_supported_records(self):
        requests = {"ko": "문서윤 씨는 음식 제한 없다던데요? 참깨 들어간 음식도 괜찮겠네요.",
                    "en": "Mun Seo-yun has no dietary restrictions. Can she eat sesame?",
                    "ja": "Mun Seo-yunさんは食事制限がないそうです。ゴマを食べてもよいですか？",
                    "zh-Hans": "Mun Seo-yun没有饮食限制，可以吃芝麻吗？",
                    "zh-Hant": "Mun Seo-yun沒有飲食限制，可以吃芝麻嗎？"}
        for language, request in requests.items():
            with self.subTest(language=language):
                result, _ = self.generated(request, request=request, language=language, docs=self.confirmed_evidence())
                first_line = result["draft"].splitlines()[0]
                self.assertIn(culture.FOOD_NEED_LABELS[language]["sesame allergy"], first_line)
                self.assertIn("2024", result["draft"])
                self.assertTrue(in_language(result["draft"], language))
                self.assertNotIn("same_name_archive", result["draft"])
        request = requests["ko"]
        result, _ = self.generated(request, request=request, docs=self.confirmed_evidence(with_archive=False))
        self.assertNotIn("2024", result["draft"])
        self.assertNotIn("동명이인", result["draft"])
        docs, verdicts = self.confirmed_evidence()
        docs["people/contacts_current.csv"] = "name,role,scope,note\n문서윤,해설사,다른 모임,제한 미확인\n"
        result, facts = self.generated(request, request=request, docs=(docs, verdicts))
        self.assertEqual(facts["required_conditions"]["confirmed_food_people"], [])
        self.assertNotIn("문서윤", result["draft"])
        self.assertNotIn("2024", result["draft"])

    def test_technical_scrubbed_good_food_answer_is_preserved(self):
        answer = "Please confirm ingredients and cross-contact with the vendor."
        result, _ = self.generated(answer, request="What can I eat?", language="en", status="partial",
                                   status_reason="technical_scrubbed", docs=self.confirmed_evidence())
        self.assertEqual(result["draft"], answer)
        self.assertEqual(result["localized"]["status_reason"], "technical_scrubbed")


if __name__ == "__main__":
    unittest.main()
