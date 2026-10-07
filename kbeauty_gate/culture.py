"""공통 테스트(기본 기능): 방문단 문화 코스 초안 + 음식 제한 한글 카드.

뷰티 기능과 같은 수집·신뢰성 하네스를 쓰고, 예약·발송 없이 output에 초안만 저장한다.
"""
import csv
import io
import json
import re
from pathlib import Path
from datetime import date
from typing import Dict, List

from . import nvidia
from .language import COPY, _korean_fallback_text, detect_language, localized_projection, normalize_locale
from .trust import Verdict

NEED_KO = {
    "vegan": "저는 비건이에요. 고기, 생선, 멸치 육수, 젓갈은 빼 주세요.",
    "peanut allergy": "땅콩 알레르기가 있어요.",
    "sesame allergy": "참깨 알레르기가 있어요. 들깨는 다른 재료지만, 들어갔는지 알려 주세요.",
    "wheelchair": "휠체어를 이용해요. 계단 없는 길이나 경사로를 알려 주세요.",
}


MONTH_NAMES = {name: month for month, names in enumerate(
    ("jan january", "feb february", "mar march", "apr april", "may", "jun june", "jul july",
     "aug august", "sep sept september", "oct october", "nov november", "dec december"), 1)
    for name in names.split()}
NUMERIC_DATE = re.compile(
    r"(?<!\d)(?:(?P<year>20\d{2})\s*(?:[-/.]|년|年)\s*)?"
    r"(?P<month>1[0-2]|0?[1-9])\s*(?:[-/.]|월|月)\s*"
    r"(?P<day>3[01]|[12]\d|0?[1-9])(?:\s*[일日])?(?!\d)")
ENGLISH_MONTH = "|".join(sorted(MONTH_NAMES, key=len, reverse=True))
ENGLISH_DATES = [re.compile(pattern, re.IGNORECASE) for pattern in (
    rf"\b(?P<month>{ENGLISH_MONTH})\.?\s+(?P<day>3[01]|[12]\d|0?[1-9])(?:st|nd|rd|th)?(?:,?\s+(?P<year>20\d{{2}}))?\b",
    rf"\b(?P<day>3[01]|[12]\d|0?[1-9])(?:st|nd|rd|th)?\s+(?P<month>{ENGLISH_MONTH})\.?(?:,?\s+(?P<year>20\d{{2}}))?\b",
)]
DATED_OPERATIONS = re.compile(r"notice|route_card|route_note|community_board|공지|운영|경로", re.IGNORECASE)


def _explicit_dates(text: str, default_year: int):
    dates = set()
    for pattern in (NUMERIC_DATE, *ENGLISH_DATES):
        for match in pattern.finditer(text or ""):
            month_text = match.group("month").lower()
            month = int(month_text) if month_text.isdigit() else MONTH_NAMES[month_text]
            try:
                dates.add(date(int(match.group("year") or default_year), month, int(match.group("day"))))
            except ValueError:
                continue
    return dates


def culture_visit_date(request: str, group_date: str) -> date:
    """Use a single explicit requested date; otherwise keep the group's scheduled date."""
    scheduled = date.fromisoformat(group_date)
    requested = _explicit_dates(request, scheduled.year)
    return next(iter(requested)) if len(requested) == 1 else scheduled


def _applicable(docs: Dict[str, str], verdicts: Dict[str, Verdict], visit: date) -> List[str]:
    """방문일을 언급하는 믿을 만한 공지 문장만 뽑는다."""
    out = []
    for name, text in docs.items():
        v = verdicts.get(name)
        if not v or not v.trusted or name.startswith("beauty/"):
            continue
        if DATED_OPERATIONS.search(name) and visit in _explicit_dates(text, visit.year):
            out.append(f"{text.strip()} ({name})")
            continue
        for sentence in re.split(r"(?<=[.다])\s+", text):
            if visit in _explicit_dates(sentence, visit.year):
                out.append(f"{sentence.strip()} ({name})")
    return out


def people_from(docs: Dict[str, str]) -> List[Dict]:
    group = json.loads(docs.get("travel/visitor_group.json", "{}") or "{}")
    current = {r["name"]: r for r in csv.DictReader(io.StringIO(docs.get("people/contacts_current.csv", "")))}
    people = []
    for p in group.get("people", []):
        row = current.get(p["name"])
        people.append({"name": p["name"], "needs": p.get("needs", []),
                       "confirmed_by": "people/contacts_current.csv" if row else "visitor_group.json만"})
    return people


def food_card(person: Dict) -> str:
    lines = [f"## {person['name']} 님 카드", "", "상인·식당에 그대로 보여 주세요.", ""]
    for need in person["needs"]:
        lines.append(f"- {NEED_KO.get(need, need + '이(가) 있어요.')}")
    lines += ["", "이 음식에 위 재료가 들어갔는지 알려 주세요. 감사합니다!", ""]
    return "\n".join(lines)


CERTAINTY = [
    ("측정 중", r"진행\s*중|측정\s*중"),
    ("판독 불확실", r"훼손|OCR|0\s*또는\s*9|가능성"),
    ("추정", r"추정|보인다|것으로\s*보|듯"),
    ("확정", r"확인했다|확인됨|공사대장"),
]


def classify_sentences(text: str) -> List[Dict]:
    """불확실 자료를 통째로 버리지 않고 문장마다 확정/추정/측정 중/판독 불확실로 나눈다."""
    out = []
    ocr = "OCR" in text
    for raw in re.split(r"(?<=[.다])\s+|\n+", text):
        if raw.strip().startswith("#"):
            continue
        sentence = raw.strip()
        if len(sentence) < 8 or sentence.startswith("["):
            sentence = sentence.split("]", 1)[-1].strip() if sentence.startswith("[") else sentence
            if len(sentence) < 8:
                continue
        label = next((name for name, pat in CERTAINTY if re.search(pat, sentence)), "근거 있음")
        if ocr and label == "근거 있음" and re.search(r"\d{4}년", sentence):
            label = "판독 불확실"
        out.append({"sentence": sentence, "certainty": label})
    return out


SOURCE_KINDS = [
    (r"tourism_leaflet|leaflet", "관광 홍보 전단"), (r"field_note", "현장 조사 메모"),
    (r"newspaper_ocr", "신문 OCR 발췌"), (r"blog_cache", "블로그 캐시"), (r"notice", "공지"),
    (r"route_card", "경로 카드"), (r"route_note", "경로 메모"), (r"interpretation_draft", "해설 초안"),
    (r"community_board", "지역 게시판"), (r"food_glossary", "음식 용어집"), (r"etiquette", "시장 예절 안내"),
]


def source_label(name: str) -> str:
    """Readable source name for the model and the screen; file paths make the model echo them."""
    stem = Path(name).stem
    date_match = re.search(r"\d{4}(?:-\d{2}-\d{2})?", stem)
    kind = next((ko for pattern, ko in SOURCE_KINDS if re.search(pattern, stem, re.IGNORECASE)), None)
    if kind is None:
        kind = re.sub(r"[_-]+", " ", re.sub(r"\d{4}(?:-\d{2}-\d{2})?", "", stem)).strip() or "참고 자료"
    return f"{date_match.group(0)} {kind}" if date_match else kind


def find_conflicts(docs: Dict[str, str], verdicts: Dict[str, Verdict]) -> List[str]:
    """광고성 '원형 보존' 주장과 현장 조사의 철거·재건 기록이 부딪히면 제외 이유로 남긴다."""
    notes = []
    restored = [n for n, t in docs.items() if re.search(r"철거|재건|보수", t) and verdicts.get(n) and verdicts[n].trusted]
    for name, text in docs.items():
        if re.search(r"원형|처음\s*모습", text) and verdicts.get(name) and not verdicts[name].trusted and restored:
            reason = f"'{source_label(name)}'의 원형 보존 주장은 {', '.join(map(source_label, restored))}의 철거·재건 기록과 충돌해 제외"
            verdicts[name].reasons.append(reason)
            notes.append(reason)
    return notes


TIME_RANGE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})\s*[~–—-]\s*(\d{1,2}):(\d{2})(?!\d)")
WHEELCHAIR_WORDS = re.compile(r"휠체어|wheelchair|車いす|車椅子|轮椅|輪椅", re.IGNORECASE)
MOVE_WORDS = re.compile(r"이동|복귀|귀환|돌아|출발|도착|walk|return|travel|transfer|移動|戻|徒歩|步行|返回|出發|出发", re.IGNORECASE)
UNCERTAINTY_WORDS = re.compile(r"확인(?:이|은|을)?\s*필요|확인되지|확인할\s*수\s*없|원문\s*확인|불확실|추정|측정\s*중|진행\s*중|가능성|보인다|것으로\s*보|미확인|"
                               r"uncertain|unconfirmed|estimated|appears?|possibly|\bmay\b|measurement|needs?\s+confirmation|(?:please\s+)?confirm\s+(?:before|the|all)|"
                               r"未確認|不確実|推定|可能性|調査中|測定中|待确认|待確認|不确定|不確定|推测|推測|测定|測定", re.IGNORECASE)


def culture_constraints(trusted: Dict[str, str], visit: date, people: List[Dict], request: str, caveats: Dict) -> Dict:
    """Extract only conditions represented by trusted, applicable source statements."""
    day_sources = [text for name, text in trusted.items()
                   if DATED_OPERATIONS.search(name) and visit in _explicit_dates(text, visit.year)]
    day_text = "\n".join(day_sources)
    window = next((match for match in TIME_RANGE.finditer(day_text)
                   if "운영" in day_text[match.end():match.end() + 20]), None)
    gate = re.search(r"([동서남북]문)\s*(?:을|를)?\s*이용(?!\s*(?:불가|금지))", day_text)
    blocked = re.findall(r"([동서남북]문)[^.\n]{0,25}(?:굴착|폐쇄|통제)", day_text)
    routes = "\n".join(text for name, text in trusted.items() if re.search(r"route|경로", name, re.IGNORECASE))
    route = re.search(r"([동서남북]문)\s*(?:→|->|에서)\s*([가-힣A-Za-z ]+?)\s*(?:까지\s*)?도보\s*(\d+)\s*분", routes)
    wheelchair = re.search(r"휠체어[^.\n]{0,80}?(\d+)\s*분", routes)
    history = [item for items in caveats.values() for item in items]
    return {
        "visit_date": visit.isoformat(),
        "market_window": [int(window[1]) * 60 + int(window[2]), int(window[3]) * 60 + int(window[4])] if window else None,
        "verified_clock_times": sorted(set(re.findall(r"(?<!\d)\d{1,2}:\d{2}(?!\d)", day_text))),
        "visit_day_operations_available": bool(day_sources),
        "required_gate": gate[1] if gate else None, "blocked_gates": sorted(set(blocked)),
        "route_origin": route[1] if route else None, "route_destination": route[2].strip() if route else None,
        "walking_minutes": int(route[3]) if route else None,
        "wheelchair_minutes": int(wheelchair[1]) if wheelchair else None,
        "wheelchair_requested": bool(WHEELCHAIR_WORDS.search(request)) or any("wheelchair" in p.get("needs", []) for p in people),
        "history_changed": any(re.search(r"철거|재건|보수", text) for name, text in trusted.items() if name.startswith("history/")),
        "uncertain_years": sorted({year for item in history if item["certainty"] in ("판독 불확실", "추정", "측정 중")
                                   for year in re.findall(r"(?<!\d)(?:18|19|20)\d{2}(?!\d)", item["sentence"])}),
        "history_statements": history,
        "verified_safe_menu_items": [],
        "unlisted_allergies": "unknown; never infer an allergy is absent",
        "food_confirmation_required": "No individual menu, ingredients or cross-contact safety is verified. Ingredient differences do not prove safety.",
    }


def validate_culture_text(text: str, constraints: Dict) -> List[str]:
    """Conservative checks for known contradictions, not a general factual proof."""
    issues = set()
    text = str(text or "")
    chunks = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s*|\n+", text) if part.strip()]
    gate_aliases = {"북문": r"북문|north\s+(?:gate|entrance)|北門|北门", "남문": r"남문|south\s+(?:gate|entrance)|南門|南门",
                    "동문": r"동문|east\s+(?:gate|entrance)|東門|东门", "서문": r"서문|west\s+(?:gate|entrance)|西門|西门"}
    for chunk in chunks:
        for gate in constraints["blocked_gates"]:
            alias = gate_aliases.get(gate, re.escape(gate))
            positive_use = rf"(?:{alias})\s*(?:에서|으로|로|을|를|통해)[^.]*?(?:이용|이동|입장|출발|도착|복귀)|(?:from|via|through|use|enter|start\s+at)\s+(?:the\s+)?(?:{alias})|(?:{alias}).{{0,15}}(?:から|を).{{0,20}}(?:利用|出発|通|移動)|(?:从|從|经|經|使用).{{0,8}}(?:{alias})"
            refusal = r"대신|이용하지|사용하지|갈\s*수\s*없|통행\s*불가|do\s+not|cannot|can't|avoid|利用しない|使用しない|不要|不能|不可"
            if re.search(positive_use, chunk, re.IGNORECASE) and not re.search(refusal, chunk, re.IGNORECASE):
                issues.add("blocked_entrance_used")
        if constraints["history_changed"]:
            original_claim = r"처음\s*모습\s*그대로|원형.{0,12}(?:그대로|완벽|보존)|preserv\w*.{0,35}(?:original|unchanged)|original.{0,25}(?:form|state).{0,20}(?:preserv|unchanged)|原形.{0,20}(?:保存|維持)|原貌.{0,20}(?:保存|保留)|原样|原樣"
            rejected_claim = r"사용하지|사용\s*자제|쓰지|금지|제외|충돌|단정.{0,8}(?:않|못|없)|보존.{0,15}(?:않|아니|아닙)|not|cannot|avoid|excluded|conflict|使用しない|断定できない|ではない|不能|并非|並非|不应|不應|不使用"
            if re.search(original_claim, chunk, re.IGNORECASE) and not re.search(rejected_claim, chunk, re.IGNORECASE):
                issues.add("unsupported_original_preservation")
            if any(year in chunk for year in constraints["uncertain_years"]) and not UNCERTAINTY_WORDS.search(chunk):
                issues.add("historical_uncertainty_omitted")
        if not constraints["verified_safe_menu_items"]:
            allergy_absence = r"알레르기(?:가|는|도)?\s*없(?:는(?!지)|다|습니다|어요|으)|(?:no|without|has\s+no|does\s+not\s+have|doesn't\s+have).{0,25}allerg(?:y|ies)|\bnot\s+allergic\b|アレルギー.{0,10}(?:ありません|がない|はない|なし|無し)|(?:没有|沒有|无|無).{0,12}(?:过敏|過敏)|不(?:会|會)?(?:过敏|過敏)"
            for absence in re.finditer(allergy_absence, chunk, re.IGNORECASE):
                before, after = chunk[max(0, absence.start() - 60):absence.start()], chunk[absence.end():absence.end() + 35]
                denied = re.search(r"(?:do\s+not|don't|cannot|can't)\s+(?:assume|infer|conclude|determine|confirm)|断定でき|不能推断|不能推斷|不要(?:认为|認為|说|說)", before, re.IGNORECASE)
                denied = denied or re.match(r"고\s*(?:단정|판단|간주).{0,15}(?:않|없|못)", after)
                if not denied:
                    issues.add("unverified_allergy_absence")
            safe_claim = r"먹을\s*수\s*있|먹어도\s*(?:되|괜찮)|섭취.{0,10}가능|(?:들깨|참깨|땅콩).{0,8}안전|안전한\s*(?:음식|메뉴|식사)|\bcan\s+eat\b|\bsafe\s+(?:to\s+eat|for|foods?|meals?)\b|(?:rice|vegetables?|fruit|perilla).{0,20}\bis\s+safe\b|安全に食べ|食べられます|安心して食べ|可以吃|可食用|安全食用"
            for claim in re.finditer(safe_claim, chunk, re.IGNORECASE):
                before, after = chunk[max(0, claim.start() - 70):claim.start()], chunk[claim.end():claim.end() + 60]
                denied = re.search(r"(?:cannot|can't)\s+(?:determine|confirm|say|guarantee).{0,45}$|\bnot\s*$|不\s*$|not\s+(?:confirmed|verified)\s*$|no\s+verified\s*$|未確認|確認でき|断定でき|不能确定|不能確定|尚未确认|尚未確認", before, re.IGNORECASE)
                denied = denied or re.match(r"(?:는지(?:는)?[^.!?。！？]{0,24}(?:확인|알\s*수\s*없)|는\s*음식으로\s*확정된\s*메뉴는\s*없|(?:하다고|하다는|을)\s*(?:단정|보장|확정).{0,15}(?:없|않|못)|하다는\s*(?:뜻|의미).{0,8}(?:아니|아닙)|(?:られる|る|られます)?とは(?:限りません|断定できません))", after)
                if not denied:
                    issues.add("unverified_food_safety")
        route_context = MOVE_WORDS.search(chunk) or re.search(r"→|->", chunk)
        if route_context:
            for duration in re.finditer(r"(?<!\d)(\d+)\s*[-－]?\s*(?:분|minutes?|mins?|分)", chunk, re.IGNORECASE):
                after = chunk[duration.end():duration.end() + 35]
                if re.search(r"(?:경로|길|route)?.{0,12}(?:사용\s*불가|이용\s*불가|사용하지|이용하지|불가능|unavailable|not\s+used)", after, re.IGNORECASE):
                    continue
                prefix = chunk[max(0, duration.start() - 45):duration.start()]
                wheelchair_duration = bool(WHEELCHAIR_WORDS.search(prefix))
                minimum = constraints["wheelchair_minutes"] if wheelchair_duration else constraints["walking_minutes"]
                if minimum and int(duration[1]) < minimum:
                    issues.add("unsupported_travel_duration")
    if constraints["market_window"] is None and any(clock not in constraints["verified_clock_times"] for clock in re.findall(r"(?<!\d)\d{1,2}:\d{2}(?!\d)", text)):
        issues.add("visit_day_hours_unverified")
    slots = list(TIME_RANGE.finditer(text))
    for index, match in enumerate(slots):
        end_of_line = text.find("\n", match.end())
        end_of_line = end_of_line if end_of_line >= 0 else len(text)
        next_slot = slots[index + 1].start() if index + 1 < len(slots) else len(text)
        line = text[match.start():min(end_of_line, next_slot)]
        start, end = int(match[1]) * 60 + int(match[2]), int(match[3]) * 60 + int(match[4])
        if end < start:
            issues.add("invalid_time_order")
        window = constraints["market_window"]
        if window and (start < window[0] or end > window[1]):
            issues.add("outside_verified_operating_window")
        if MOVE_WORDS.search(line):
            wheelchair_line = WHEELCHAIR_WORDS.search(line) and not re.search(r"경우|사용\s*시|이용\s*시|미지정|\bif\b|optional|場合|如果", line, re.IGNORECASE)
            minimum = constraints["wheelchair_minutes"] if constraints["wheelchair_requested"] or wheelchair_line else constraints["walking_minutes"]
            if minimum and end - start < minimum:
                issues.add("insufficient_travel_time")
    if not constraints["visit_day_operations_available"]:
        for chunk in chunks:
            if re.search(r"북문|north\s+(?:gate|entrance)|北門|北门", chunk, re.IGNORECASE) and MOVE_WORDS.search(chunk) and not UNCERTAINTY_WORDS.search(chunk):
                issues.add("visit_day_access_unverified")
    return sorted(issues)


def _verified_korean_summary(constraints: Dict) -> str:
    lines = ["생성된 코스의 일부 내용을 확인할 수 없어, 자료에서 확인된 조건만 정리합니다."]
    window = constraints["market_window"]
    if window:
        hours = [f"{value // 60:02d}:{value % 60:02d}" for value in window]
        lines.append(f"{constraints['visit_date']} 시장 운영은 {hours[0]}–{hours[1]}입니다.")
        if constraints["required_gate"]:
            lines.append(f"입장은 {constraints['required_gate']}을 이용합니다.")
        if constraints["walking_minutes"]:
            lines.append(f"{constraints['route_origin']}→{constraints['route_destination']} 도보 이동은 {constraints['walking_minutes']}분입니다.")
        if constraints["wheelchair_minutes"]:
            lines.append(f"휠체어 이용 시 우회 경로는 약 {constraints['wheelchair_minutes']}분입니다. 복귀 경로와 소요시간은 별도로 확인하고 충분한 시간을 확보해야 합니다.")
    else:
        lines.append(f"{constraints['visit_date']}의 운영 시간과 출입·이동 조건은 확인되지 않았습니다. 확정 시간표를 제시하지 않으며 방문 전에 확인이 필요합니다.")
    lines.extend(_korean_fallback_text(f"[{item['certainty']}] {item['sentence']}", "연혁 확인이 필요합니다.") for item in constraints["history_statements"])
    lines.append("먹을 수 있는 음식으로 확정된 메뉴는 없습니다. 재료·육수·젓갈·알레르기 성분과 교차접촉을 상인에게 확인하고, 확인되지 않으면 섭취하지 않는 편이 안전합니다. 미기재된 알레르기는 없다고 단정하지 않습니다.")
    lines.append("초안만 작성했으며 예약·발송·결제는 하지 않았습니다.")
    return "\n".join(lines)


def guard_culture_projection(localized: Dict, constraints: Dict, notices: List[str], caveats: List[str]):
    """Replace only failed fields; retain no unsafe generated text in the report."""
    out = dict(localized)
    language = normalize_locale(localized.get("language"))
    replaced = []
    draft_issues = validate_culture_text(out.get("draft", ""), constraints)
    if draft_issues:
        out["draft"] = _verified_korean_summary(constraints) if language == "ko" else COPY[language]["draft"]
        replaced.append({"field": "draft", "reasons": draft_issues})
    for field, source, default in (("notices", notices, "notice"), ("caveats", caveats, "caveat"), ("route_notes", [], "route")):
        values = list(out.get(field) or [])
        for index, value in enumerate(values):
            issues = validate_culture_text(value, constraints)
            if issues:
                original = source[index] if index < len(source) else ""
                values[index] = _korean_fallback_text(original, COPY[language][default]) if language == "ko" else COPY[language][default]
                replaced.append({"field": f"{field}[{index}]", "reasons": issues})
        out[field] = values
    if replaced:
        out["status"] = "fallback" if draft_issues or localized.get("status") == "fallback" else "partial"
        out["status_reason"] = "evidence_conflict"
    return out, {"replaced_fields": replaced}


def run_culture(docs: Dict[str, str], verdicts: Dict[str, Verdict], request: str, settings, language=None) -> Dict:
    group = json.loads(docs.get("travel/visitor_group.json", "{}") or "{}")
    scheduled = date.fromisoformat(group.get("date", date.today().isoformat()))
    visit = culture_visit_date(request, scheduled.isoformat())
    people = people_from(docs)
    notices = _applicable(docs, verdicts, visit)
    trusted = {n: t for n, t in docs.items()
               if not n.startswith("beauty/") and n in verdicts and verdicts[n].trusted}
    if visit != scheduled:
        trusted = {name: text for name, text in trusted.items()
                   if not (DATED_OPERATIONS.search(name) and _explicit_dates(text, scheduled.year)
                           and visit not in _explicit_dates(text, scheduled.year))}
        if not notices:
            notices.append(f"{visit.isoformat()}의 운영 시간·출입구·이동 조건을 확인할 당일 공지가 없습니다. "
                           "다른 날짜의 운영 조건은 그대로 적용할 수 없으므로 방문 전에 확인이 필요합니다.")
    caveats = {n: classify_sentences(docs[n]) for n in trusted if "uncertain" in verdicts[n].flags}
    conflicts = find_conflicts(docs, verdicts)
    language = normalize_locale(language) if language else detect_language(request)
    constraints = culture_constraints(trusted, visit, people, request, caveats)
    caveat_texts = [f"[{item['certainty']}] {item['sentence']}" for items in caveats.values() for item in items] + conflicts

    facts = {
        "request": request,
        "visit_date": visit.isoformat(),
        "approval": group.get("approval", "draft_only"),
        "people": people,
        "notices_for_visit_date": notices,
        "trusted_sources": {source_label(n): t for n, t in trusted.items()},
        "statements_by_certainty": {source_label(n): items for n, items in caveats.items()},
        "excluded_due_to_conflict": conflicts,
        "required_conditions": constraints,
    }
    localized = localized_projection(
        settings, language, "culture", facts, notices=notices,
        caveats=caveat_texts,
        proper_names=[p["name"] for p in people] + ["해담 옛시장", "해담", "성진정"],
    )
    localized, validation = guard_culture_projection(localized, constraints, notices, caveat_texts)
    return {"visit_date": visit.isoformat(), "people": people, "notices": notices,
            "language": language, "localized": localized,
            "draft": localized["draft"], "uncertain": caveats, "conflicts": conflicts,
            "culture_validation": validation}
