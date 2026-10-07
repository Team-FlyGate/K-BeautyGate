"""생성 답변 사후 검사: 모델이 검증된 근거를 어긴 문장을 내보내기 전에 걸러 낸다.

공통 과제 실측(workspace/notes/astra_scenario_checks_1430.md)에서 나온 실패 유형을 규칙으로 막는다.
- 걸러 낸 옛 경로(남문 해안 데크 12분)를 채택
- 성진정을 '원형 그대로 보존'이라고 단정 (1987 별채 철거 기록과 충돌)
- 근거 없는 음식 안전 단정, 기록에 없는 '알레르기 없음' 단정
- 휠체어 우회(약 28분)를 그보다 짧은 시간 칸에 배정한 시간표
걸린 문장은 빼고, 근거에 맞는 정정 문장을 사용자 언어로 덧붙인다.
"""
import re
from typing import Dict, List, Tuple

NEGATION = re.compile(r"않|없|금지|말아|쓰지|아니|제외|자제|삼가|충돌|주장은|단정할\s*수|not|n't|never|avoid|exclud|cannot|"
                      r"\bno\b|ない|ません|除外|控え|不|未|别|別|排除", re.IGNORECASE)
# 분명한 안전 단정: 확인 권고가 같이 있어도 항상 잡는다
STRONG_FOOD = re.compile(
    r"(들깨|참깨|땅콩|perilla|sesame|peanut|エゴマ|ごま|ゴマ|苏子|紫苏|芝麻|花生)\s*(은|는|도|is|are|は|也)?\s*(안전|괜찮|safe|fine|大丈夫|安全)|"
    r"can eat|safe to eat|먹어도\s*(되|괜찮)|먹을\s*수\s*있|食べられ(る|ます)|可以吃|能吃", re.IGNORECASE)
CONFIRM = re.compile(r"확인|물어|문의|confirm|check|ask|確認|确认|询问|詢問", re.IGNORECASE)

RULES = [
    ("old_route", re.compile(
        r"(남문.{0,25}(해안\s*데크|12\s*분))|((해안\s*데크).{0,20}12\s*분)|(south\s*gate.{0,40}(deck|12\s*min))|"
        r"(南門.{0,25}(デッキ|12\s*分|木栈道|棧道|12\s*分钟|12\s*分鐘))|(南门.{0,25}(12\s*分|栈道))", re.IGNORECASE), False),
    ("original_form", re.compile(
        r"원형.{0,8}(그대로|보존|완벽)|처음\s*모습\s*그대로|original\s+(form|state|condition)|perfectly\s+preserved|"
        r"原形.{0,6}(そのまま|保存|保持)|当時のまま|原貌|原样|原樣|完整保存", re.IGNORECASE), True),
    ("food_safety", re.compile(
        r"((들깨|참깨|땅콩|음식|메뉴|반찬|떡|간식|perilla|sesame|peanut|food|dish|rice|vegetable|fruit|"
        r"エゴマ|ごま|ゴマ|ピーナッツ|料理|食べ物|苏子|紫苏|芝麻|花生|食物).{0,40}"
        r"(안전|괜찮|먹어도|먹을\s*수\s*있|safe|fine to eat|can eat|okay to eat|大丈夫|食べられ|安全|可以吃|能吃))|"
        r"((안전|safe|大丈夫|安全).{0,20}(들깨|참깨|perilla|sesame|エゴマ|ごま|苏子|芝麻))|"
        r"((can eat|safe to eat|먹어도\s*되|먹을\s*수\s*있|食べられ|可以吃|能吃).{0,40}"
        r"(rice|vegetable|fruit|dish|food|음식|반찬|떡|料理|ご飯|野菜|食物|米饭|蔬菜))", re.IGNORECASE), True),
    ("no_allergy", re.compile(
        r"알레르기(가)?\s*없|알레르기\s*걱정\s*없|no\s+\w*\s*allerg|not\s+allergic|without\s+(any\s+)?allerg|"
        r"アレルギー(は|が)?(ない|ありません)|没有.{0,6}过敏|沒有.{0,6}過敏|无过敏|無過敏", re.IGNORECASE), False),
]

FIX = {
    "old_route": {
        "ko": "남문 해안 데크 12분 경로는 공사 이전 자료라 쓰지 않았어요. 시장 북문→성진정은 도보 약 18분, 휠체어는 버스정류장 쪽 우회로 약 28분이에요.",
        "en": "The old south-gate deck route (12 min) predates the roadworks, so it was not used. From the market's north gate to Seongjinjeong it is about 18 min on foot, or about 28 min via the wheelchair detour.",
        "ja": "南門から海岸デッキで12分という経路は工事前の資料なので使いませんでした。市場の北門から城津亭まで徒歩約18分、車いすはバス停側の迂回路で約28分です。",
        "zh-Hans": "南门海岸栈道12分钟的路线是施工前的资料，因此没有采用。从市场北门到城津亭步行约18分钟，轮椅需绕行约28分钟。",
        "zh-Hant": "南門海岸棧道12分鐘的路線是施工前的資料，因此沒有採用。從市場北門到城津亭步行約18分鐘，輪椅需繞行約28分鐘。"},
    "original_form": {
        "ko": "성진정은 1987년 보수 때 동쪽 별채가 철거된 기록이 있어 '원형 그대로 보존'이라고 소개하지 않아요. 현판은 1961년 재건 때 새로 만든 것으로 보이며, 본채 일부 연대는 측정 중이에요.",
        "en": "Records show Seongjinjeong's east annex was removed during 1987 repairs, so it is not described as 'preserved in its original form'. The signboard appears to date from the 1961 rebuild, and dating of parts of the main hall is ongoing.",
        "ja": "城津亭は1987年の補修で東側の別棟が撤去された記録があるため、「原形のまま保存」とは紹介しません。扁額は1961年の再建時に新調されたとみられ、本棟の一部は年代測定中です。",
        "zh-Hans": "记录显示城津亭东侧别栋在1987年维修时被拆除，因此不称其为“原貌保存”。匾额推测为1961年重建时新制，主体部分年代仍在测定中。",
        "zh-Hant": "紀錄顯示城津亭東側別棟在1987年維修時被拆除，因此不稱其為「原貌保存」。匾額推測為1961年重建時新製，主體部分年代仍在測定中。"},
    "food": {
        "ko": "자료에 확인된 메뉴·재료 정보가 없어 어떤 음식도 안전하다고 말할 수 없어요. 들깨와 참깨는 다른 재료지만 들어갔는지 꼭 확인하고, 음식 카드를 상인에게 보여 주세요.",
        "en": "There is no verified menu or ingredient information, so no dish can be called safe. Perilla and sesame are different, but always ask whether either is used, and show the food card to the vendor.",
        "ja": "確認済みのメニュー・材料情報がないため、どの料理も安全とは言えません。エゴマとゴマは別の材料ですが、使われているか必ず確認し、食事カードを店の人に見せてください。",
        "zh-Hans": "没有经过核实的菜单或食材信息，因此不能说任何食物是安全的。苏子和芝麻是不同的食材，但请务必确认是否使用，并把饮食卡片给商家看。",
        "zh-Hant": "沒有經過核實的菜單或食材資訊，因此不能說任何食物是安全的。蘇子和芝麻是不同的食材，但請務必確認是否使用，並把飲食卡片給商家看。"},
    "timetable": {
        "ko": "휠체어 우회 구간은 약 28분이 걸려요. 시간표의 해당 칸은 최소 28분으로 잡아 주세요.",
        "en": "The wheelchair detour takes about 28 minutes; allow at least 28 minutes for that leg.",
        "ja": "車いすの迂回区間は約28分かかります。その区間は最低28分を確保してください。",
        "zh-Hans": "轮椅绕行路段约需28分钟，该时段请至少预留28分钟。",
        "zh-Hant": "輪椅繞行路段約需28分鐘，該時段請至少預留28分鐘。"},
}
TIME_RANGE = re.compile(r"(\d{1,2}):(\d{2})\s*[~\-–—〜～]\s*(\d{1,2}):(\d{2})")
DETOUR_28 = re.compile(r"28\s*(분|min|分)", re.IGNORECASE)


def _units(text: str) -> List[str]:
    """줄 단위로 나누고, 표가 아닌 줄은 문장 단위로 다시 나눈다."""
    out = []
    for line in text.split("\n"):
        if line.strip().startswith("|") or not line.strip():
            out.append(line)
        else:
            out.extend(re.split(r"(?<=[.!?。！？])\s+", line))
    return out


def _short_detour(unit: str) -> bool:
    if not DETOUR_28.search(unit):
        return False
    for h1, m1, h2, m2 in TIME_RANGE.findall(unit):
        if (int(h2) * 60 + int(m2)) - (int(h1) * 60 + int(m1)) < 28:
            return True
    return False


def check_text(text: str, language: str = "ko") -> Tuple[str, List[Dict]]:
    """(정리된 텍스트, 걸린 항목 목록). 걸린 문장·표 행은 빼고 정정 문장을 끝에 붙인다."""
    if not text:
        return text, []
    lang = language if language in FIX["food"] else "en"
    hits, kept, fixes = [], [], []
    for unit in _units(text):
        rule = None
        for name, pattern, allow_negated in RULES:
            if pattern.search(unit):
                strong = name == "food_safety" and STRONG_FOOD.search(unit) and not re.search(
                    r"cannot|can't|not\s+safe|없|않|ない|不", unit, re.IGNORECASE)
                if not strong:
                    if allow_negated and NEGATION.search(unit):
                        continue  # "'원형 그대로' 표현은 쓰지 않아요", "안전하다고 단정할 수 없어요" 같은 부정문은 통과
                    if name == "food_safety" and CONFIRM.search(unit):
                        continue  # "재료를 확인한 뒤 고르세요" 같은 확인 권고는 통과
                rule = name
                break
        if rule is None and _short_detour(unit):
            rule = "timetable"
        if rule:
            hits.append({"rule": rule, "removed": unit.strip()})
            key = "food" if rule in ("food_safety", "no_allergy") else rule
            if FIX[key][lang] not in fixes:
                fixes.append(FIX[key][lang])
            continue
        kept.append(unit)
    if not hits:
        return text, []
    body = "\n".join(u for u in kept).strip()
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body + "\n\n" + "\n".join(f"- {f}" for f in fixes), hits


# ---- K-뷰티 답변: "금지 성분 없음"을 "안전·기준 충족"으로 부풀린 표현 ----
SAFETY_CLAIM = re.compile(
    r"안전한\s*(제품|화장품|선택)|안전하게\s*(사용|쓰)|안심하고\s*(사용|쓰|바르)|"
    r"(기준|규정|규제)(을|에|를)?\s*(충족|만족|부합|통과)|문제\s*없는\s*(제품|성분)|"
    r"safe\s+(product|choice|to\s+use|for\s+your)|meets?\s+.{0,30}(standard|requirement|regulation)|"
    r"(fully\s+)?compliant\s+with|"
    r"安全な(製品|商品|化粧品|選択)|安心して(使え|使用|お使い)|基準を満た|基準に適合|"
    r"安全的(产品|產品|化妆品|化妝品)|放心(使用|选购|選購)|符合.{0,12}(标准|標準|规定|規定)", re.IGNORECASE)
BEAUTY_FIX = {
    "ko": "확인한 공식 금지 성분 목록에 해당하는 성분은 없었어요. 피부에 맞는지는 사람마다 다르니 사용 전 테스트를 권해요.",
    "en": "None of its ingredients appear on the official banned lists we checked. That is not a guarantee it suits your skin, so patch-test first.",
    "ja": "確認した公的な禁止成分リストに該当する成分はありませんでした。肌に合うかは人それぞれなので、使う前にパッチテストをおすすめします。",
    "zh-Hans": "成分不在我们核对的官方禁用成分清单中。这并不代表一定适合您的皮肤，使用前建议先做局部测试。",
    "zh-Hant": "成分不在我們核對的官方禁用成分清單中。這並不代表一定適合您的皮膚，使用前建議先做局部測試。",
}


def check_beauty(text: str, language: str = "ko") -> Tuple[str, List[Dict]]:
    """안전·기준 충족 단정 문장을 빼고, 사실만 말하는 문장 하나로 바꾼다."""
    if not text:
        return text, []
    lang = language if language in BEAUTY_FIX else "en"
    hits, kept = [], []
    for unit in _units(text):
        if SAFETY_CLAIM.search(unit) and not re.search(r"보장할\s*수\s*없|아니|not\s+a\s+guarantee|cannot|ではありません|不代表|不保证|不保證", unit, re.IGNORECASE):
            hits.append({"rule": "safety_claim", "removed": unit.strip()})
            continue
        kept.append(unit)
    if not hits:
        return text, []
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(kept).strip())
    sep = " " if body and "\n" not in body else "\n\n"
    return (body + sep + BEAUTY_FIX[lang]).strip(), hits
