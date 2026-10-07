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
CLOCK_TIME = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)")
WHEELCHAIR_WORDS = re.compile(r"휠체어|wheelchair|車いす|車椅子|轮椅|輪椅", re.IGNORECASE)
MOVE_WORDS = re.compile(r"이동|복귀|귀환|돌아|출발|도착|walk|return|travel|transfer|移動|戻|徒歩|步行|返回|出發|出发", re.IGNORECASE)
RETURN_WORDS = re.compile(r"복귀|귀환|돌아|\breturn|戻|帰着|返回", re.IGNORECASE)
UNCERTAINTY_WORDS = re.compile(r"확인(?:이|은|을)?\s*필요|확인되지|확인할\s*수\s*없|원문\s*확인|불확실|추정|측정\s*중|진행\s*중|가능성|보인다|것으로\s*보|미확인|"
                               r"uncertain|unconfirmed|estimated|appears?|possibly|\bmay\b|measurement|needs?\s+confirmation|(?:please\s+)?confirm\s+(?:before|the|all)|"
                               r"未確認|不確実|推定|可能性|調査中|測定中|待确认|待確認|不确定|不確定|推测|推測|测定|測定", re.IGNORECASE)


def culture_constraints(trusted: Dict[str, str], visit: date, people: List[Dict], request: str, caveats: Dict,
                        current_people_csv: str = "") -> Dict:
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
    # Structured current-contact input has no document verdict in collect().
    current = {row["name"]: row for row in csv.DictReader(io.StringIO(current_people_csv))}
    need_terms = {"vegan": "비건", "peanut allergy": "땅콩 알레르기", "sesame allergy": "참깨 알레르기"}
    confirmed_people = []
    for person in people:
        row = current.get(person["name"], {})
        needs = [need for need in person.get("needs", [])
                 if need in need_terms and need_terms[need] in row.get("note", "")]
        if row.get("role") == "방문객" and needs:
            confirmed_people.append({"name": person["name"], "needs": needs})
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
        "confirmed_food_people": confirmed_people,
        "same_name_records": [],
        "perilla_is_distinct": bool(re.search(r"들깨.{0,20}참깨.{0,15}(?:다르|다른)", trusted.get("culture/food_glossary.md", ""))),
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
            safe_claim = r"먹을\s*수\s*있|먹어도\s*(?:되|괜찮)|섭취.{0,10}가능|(?:들깨|참깨|땅콩).{0,8}안전|안전한\s*(?:음식|메뉴|식사)|(?:비건|알레르기).{0,12}(?:완벽|완전|100%).{0,8}(?:대응|보장|안전)|\bcan\s+eat\b|\bsafe\s+(?:to\s+eat|for|foods?|meals?)\b|(?:rice|vegetables?|fruit|perilla).{0,20}\bis\s+safe\b|安全に食べ|食べられます|安心して食べ|可以吃|可食用|安全食用"
            for claim in re.finditer(safe_claim, chunk, re.IGNORECASE):
                before, after = chunk[max(0, claim.start() - 70):claim.start()], chunk[claim.end():claim.end() + 60]
                after = after.lstrip("'\"‘’“”")
                denied = re.search(r"(?:cannot|can't)\s+(?:determine|confirm|say|guarantee).{0,45}$|\bnot\s*$|不\s*$|not\s+(?:confirmed|verified)\s*$|no\s+verified\s*$|未確認|確認でき|断定でき|不能确定|不能確定|尚未确认|尚未確認", before, re.IGNORECASE)
                denied = denied or re.match(r"(?:(?:는지(?:는)?|인지)[^.!?。！？]{0,24}(?:확인|알\s*수\s*없)|는\s*음식으로\s*확정된\s*메뉴는\s*없|(?:하다고|하다는|이라고|이라는|을)\s*(?:단정|보장|확정).{0,15}(?:없|않|못)|(?:이라는|이라고).{0,18}(?:확인되지|입증되지|검증되지|근거.{0,5}없)|하다는\s*(?:뜻|의미).{0,8}(?:아니|아닙)|(?:られる|る|られます)?とは(?:限りません|断定できません))", after)
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
    # A single return timestamp still needs travel time after the previous visit.
    clocks = list(CLOCK_TIME.finditer(text))
    for index, clock in enumerate(clocks):
        if any(slot.start() <= clock.start() < slot.end() for slot in slots):
            continue
        prior = next((slot for slot in reversed(slots) if slot.end() <= clock.start()), None)
        if not prior or not index or clocks[index - 1].end() != prior.end():
            continue
        previous = text[prior.end():clock.start()].split("\n", 1)[0]
        following = text[clock.end():clocks[index + 1].start() if index + 1 < len(clocks) else len(text)].split("\n", 1)[0]
        destination = constraints["route_destination"]
        origin = gate_aliases.get(constraints["route_origin"], re.escape(constraints["route_origin"] or ""))
        if not destination or destination not in previous or RETURN_WORDS.search(previous):
            continue
        if not origin or not re.search(origin, following, re.IGNORECASE) or not RETURN_WORDS.search(following):
            continue
        if re.search(r"복귀.{0,8}(?:불가|불가능|못)|return.{0,12}(?:impossible|not\s+possible)", following, re.IGNORECASE):
            continue
        minimum = constraints["wheelchair_minutes"] if constraints["wheelchair_requested"] or WHEELCHAIR_WORDS.search(following) else constraints["walking_minutes"]
        previous_end = int(prior[3]) * 60 + int(prior[4])
        arrival = int(clock[1]) * 60 + int(clock[2])
        if minimum and arrival - previous_end < minimum:
            issues.add("insufficient_travel_time")
    if not constraints["visit_day_operations_available"]:
        for chunk in chunks:
            if re.search(r"북문|north\s+(?:gate|entrance)|北門|北门", chunk, re.IGNORECASE) and MOVE_WORDS.search(chunk) and not UNCERTAINTY_WORDS.search(chunk):
                issues.add("visit_day_access_unverified")
    return sorted(issues)


def _verified_korean_summary(constraints: Dict, request: str = "") -> str:
    """모델 초안이 검증을 통과하지 못하면, 확인된 조건만으로 읽을 수 있는 코스 초안을 만든다."""
    clock = lambda minutes: f"{minutes // 60:02d}:{minutes % 60:02d}"
    lines = [f"반나절 문화 코스 초안 ({constraints['visit_date']})", ""]
    window, gate = constraints["market_window"], constraints["required_gate"]
    origin, destination = constraints["route_origin"], constraints["route_destination"]
    walk, wheel = constraints["walking_minutes"], constraints["wheelchair_minutes"]
    travel = max(walk or 0, wheel or 0)  # 휠체어 우회까지 들어가도록 긴 쪽으로 잡는다
    lines.append("코스")
    if window:
        open_, close = window
        market_end = min(open_ + 90, close - travel - 60)
        if travel and destination and market_end - open_ >= 30:
            arrive = market_end + travel
            lines.append(f"1. {clock(open_)} 해담 옛시장 입장" + (f" ({gate} 이용)" if gate else ""))
            lines.append(f"2. {clock(open_)}–{clock(market_end)} 옛시장 둘러보기 · 음식은 아래 확인 후 구매")
            lines.append(f"3. {clock(market_end)}–{clock(arrive)} {origin}→{destination} 이동 (도보 {walk}분"
                         + (f", 휠체어 우회 약 {wheel}분까지 여유" if wheel else "") + ")")
            lines.append(f"4. {clock(arrive)}–{clock(arrive + 40)} {destination} 관람·해설")
            lines.append(f"5. 이후 복귀 · 복귀 경로와 시간은 현장에서 확인하고, 시장은 {clock(close)}에 닫아요")
        else:
            lines.append(f"시장 운영 시간은 {clock(open_)}–{clock(close)}이에요. 이 안에서 옛시장과 {destination or '성진정'}을 둘러보세요.")
        if constraints["blocked_gates"]:
            lines.append(f"· {', '.join(constraints['blocked_gates'])}은 공사로 이용할 수 없어요." + (f" {gate}으로 다니세요." if gate else ""))
    else:
        lines.append(f"{constraints['visit_date']}의 운영 시간과 출입·이동 조건은 확인되지 않았어요. 확정 시간표 없이 방문 전에 확인이 필요해요.")
    history = constraints["history_statements"]
    if history:
        lines += ["", "성진정 해설"]
        for label in ("확정", "추정", "측정 중", "판독 불확실"):
            sentences = [item["sentence"].rstrip(".") for item in history if item["certainty"] == label]
            if sentences:
                lines.append(f"· {label}: " + " / ".join(sentences))
        if constraints["history_changed"]:
            lines.append("· 1987년 별채 철거와 재건 기록이 있어, 지금 모습이 처음 그대로는 아니에요.")
    lines += ["", "음식"] + [f"· {line}" for line in _food_guidance("ko", constraints, request).split("\n")]
    lines += ["", "초안만 작성했어요. 예약·발송·결제는 하지 않았어요."]
    return "\n".join(lines)


FOOD_GUIDANCE = {
    "ko": "먹을 수 있는 음식으로 확정된 메뉴는 없습니다. 업소마다 원재료·육수·젓갈 사용 여부, 본인에게 해당하는 알레르기 성분과 교차접촉을 확인하세요. 확인할 수 없다면 먹지 마세요. 미기재된 알레르기는 없다고 단정하지 않습니다.",
    "en": "The available information does not confirm any menu item as suitable for you. Ask each vendor about ingredients, broth, salted fermented seafood, your relevant allergens and cross-contact. If these cannot be confirmed, do not eat it. Unlisted allergies remain unknown.",
    "ja": "提供された資料だけでは、食べられると確認できたメニューはありません。各店舗で原材料、だし、塩辛などの発酵魚介類、ご自身のアレルゲン、調理器具などを介した交差接触を確認してください。確認できなければ食べないでください。記録されていないアレルギーの有無は不明です。",
    "zh-Hans": "现有资料无法确认任何菜单菜品适合您食用。请逐店确认原料、汤底、发酵海鲜、您需要避开的过敏原及交叉接触情况。无法确认时，请勿食用。未记录的过敏情况仍属未知。",
    "zh-Hant": "現有資料無法確認任何菜單品項適合您食用。請逐店確認原料、湯底、發酵海鮮、您需要避開的過敏原及交叉接觸情況。無法確認時，請勿食用。未記錄的過敏情況仍屬未知。",
}

FOOD_NEED_LABELS = {
    "ko": {"vegan": "비건", "peanut allergy": "땅콩 알레르기", "sesame allergy": "참깨 알레르기"},
    "en": {"vegan": "vegan", "peanut allergy": "peanut allergy", "sesame allergy": "sesame allergy"},
    "ja": {"vegan": "ヴィーガン", "peanut allergy": "ピーナッツアレルギー", "sesame allergy": "ゴマアレルギー"},
    "zh-Hans": {"vegan": "纯素食", "peanut allergy": "花生过敏", "sesame allergy": "芝麻过敏"},
    "zh-Hant": {"vegan": "純素食", "peanut allergy": "花生過敏", "sesame allergy": "芝麻過敏"},
}
FOOD_NAMES = {"문서윤": "Mun Seo-yun"}


def _food_guidance(language: str, constraints: Dict, request: str) -> str:
    people = constraints.get("confirmed_food_people", [])
    names = lambda person: person["name"] if language == "ko" else FOOD_NAMES.get(person["name"], person["name"])
    restriction = lambda person: ", ".join(FOOD_NEED_LABELS[language][need] for need in person["needs"] if need in FOOD_NEED_LABELS[language])
    false_absence = r"음식\s*제한.{0,8}없|알레르기.{0,8}없|no\s+(?:dietary|food)\s+restrictions?|no\s+allerg|食事制限.{0,8}(?:ない|なし|ありません)|アレルギー.{0,8}(?:ない|なし|ありません)|(?:没有|沒有|无|無).{0,8}(?:饮食限制|飲食限制|过敏|過敏)"
    corrected = [person for person in people if any(
        any(alias.casefold() in chunk.casefold() for alias in (person["name"], FOOD_NAMES.get(person["name"], person["name"])))
        and re.search(false_absence, chunk, re.IGNORECASE)
        for chunk in re.split(r"[.!?。！？\n]+", request))]
    headers = {"ko": "현재 방문단에서 확인된 음식 제한", "en": "Confirmed dietary needs of the current visiting group",
               "ja": "現在の訪問グループで確認された食事上の条件", "zh-Hans": "当前访问团已确认的饮食限制", "zh-Hant": "目前訪問團已確認的飲食限制"}
    corrections = {"ko": "현재 방문단 {name} 님은 {needs}가 확인되어, 음식 제한이 없다는 전제는 맞지 않습니다.",
                   "en": "For the current group, {name} has confirmed dietary needs: {needs}. The claim of no dietary restrictions is incorrect.",
                   "ja": "現在の訪問グループの{name}さんには、{needs}という条件が確認されています。食事制限がないという前提は誤りです。",
                   "zh-Hans": "当前访问团的{name}已确认有以下饮食限制：{needs}。没有饮食限制的前提不正确。",
                   "zh-Hant": "目前訪問團的{name}已確認有以下飲食限制：{needs}。沒有飲食限制的前提不正確。"}
    archive_text = {"ko": "음식 제한 없음 기록은 {year}년 청소년 해설사인 동명이인의 것으로, 현재 방문단에 적용하지 않았습니다.",
                    "en": "The no-restrictions record concerns a different person with the same name, a youth guide in {year}; it does not apply to this group.",
                    "ja": "食事制限なしという記録は、{year}年の青少年ガイドを務めた同姓同名の別人のもので、現在の訪問グループには適用していません。",
                    "zh-Hans": "没有饮食限制的记录属于{year}年的同名青少年讲解员，与当前访问团无关，因此未采用。",
                    "zh-Hant": "沒有飲食限制的記錄屬於{year}年的同名青少年導覽員，與目前訪問團無關，因此未採用。"}
    lines = [corrections[language].format(name=names(person), needs=restriction(person)) for person in corrected]
    for record in constraints.get("same_name_records", []):
        if any(person["name"] == record["name"] for person in corrected):
            lines.append(archive_text[language].format(year=record["year"]))
    if people:
        lines.append(headers[language] + ": " + "; ".join(f"{names(person)}: {restriction(person)}" for person in people) + ".")
    if constraints.get("perilla_is_distinct") and any("sesame allergy" in person["needs"] for person in people):
        lines.append({"ko": "들깨는 참깨와 다른 재료지만, 사용 여부와 교차접촉은 업소에 확인해야 합니다.",
                      "en": "Perilla and sesame are different ingredients; ask the vendor about their use and cross-contact.",
                      "ja": "エゴマとゴマは別の食材ですが、使用の有無や交差接触は店舗に確認してください。",
                      "zh-Hans": "紫苏籽和芝麻是不同的食材，但使用情况和交叉接触仍需向店家确认。",
                      "zh-Hant": "紫蘇籽和芝麻是不同的食材，但使用情況和交叉接觸仍需向店家確認。"}[language])
    return "\n".join(lines + [FOOD_GUIDANCE[language]])


def _food_only_request(request: str) -> bool:
    food = r"먹|음식|식사|메뉴|비건|알레르기|\beat\b|\bfood\b|\bmeals?\b|\bmenu\b|\bvegan\b|allerg|食べ|食事|料理|メニュー|ヴィーガン|ビーガン|アレルギー|吃|食物|素食|纯素|純素|过敏|過敏"
    other_scope = r"문화|코스|동선|성진정|해설|연혁|예약|발송|메일|결제|케이터링|culture|itinerary|\broute\b|\btour\b|history|pavilion|\bbook\b|reserv|cater|\bsend\b|email|payment|\bpay\b|文化|コース|ルート|歴史|解説|予約|送信|支払|行程|路线|路線|历史|歷史|预订|預訂|预约|預約|发送|發送|邮件|郵件|付款"
    return bool(re.search(food, request, re.IGNORECASE)) and not re.search(other_scope, request, re.IGNORECASE)


def guard_culture_projection(localized: Dict, constraints: Dict, notices: List[str], caveats: List[str], request: str = ""):
    """Replace only failed fields; retain no unsafe generated text in the report."""
    out = dict(localized)
    language = normalize_locale(localized.get("language"))
    replaced = []
    draft_issues = validate_culture_text(out.get("draft", ""), constraints)
    normalize_echo = lambda value: re.sub(r"\s+", " ", str(value or "")).strip(" \"'‘’“”`.!?。！？").casefold()
    if normalize_echo(request) and normalize_echo(out.get("draft")) == normalize_echo(request):
        draft_issues.append("request_echo")
    food_request = not constraints["verified_safe_menu_items"] and _food_only_request(request)
    upstream_failure = not draft_issues and localized.get("status") == "fallback" and food_request
    if upstream_failure:
        draft_issues.append("upstream_fallback")
    if draft_issues:
        if food_request:
            out["draft"] = _food_guidance(language, constraints, request)
        else:
            out["draft"] = _verified_korean_summary(constraints, request) if language == "ko" else COPY[language]["draft"]
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
        out["status_reason"] = localized.get("status_reason", "upstream_fallback") if upstream_failure else "evidence_conflict"
    return out, {"replaced_fields": replaced}


PLACE_PATTERNS = (
    re.compile(r"[가-힣]{2,10}(?:시장|궁(?!금)|공원|마을|타워|박물관|미술관|해수욕장|산성|성당|사찰|대교)"),
    re.compile(r"\b(?:[A-Z][a-z]+\s)*[A-Z][a-z]+\s(?:Palace|Market|Temple|Park|Village|Tower|Museum|Beach|Fortress|Bridge)\b"),
    re.compile(r"[一-龥ァ-ヶー]{2,8}(?:市場|市场|宮|宫|寺|公園|公园|村|タワー|塔|博物館|博物馆)"),
)
GENERIC_PLACE = re.compile(r"(?:전통|재래|동네|근처|주변|야|수산|농수산|어느|그|이)\s*(?:시장|공원|마을|박물관)|(?:Traditional|Local|Night|Fish|The|A)\s(?:Market|Park|Village|Museum)|(?:传统|傳統|夜|附近|在)(?:市场|市場|公园|公園)", re.IGNORECASE)
KNOWN_PLACE = re.compile(r"해담|성진|haedam|seongjin|ヘダム|ソンジン|海潭|海談|城鎮|城镇|成鎮|成镇", re.IGNORECASE)
UNLISTED_PLACE = {
    "ko": "요청하신 {places}은(는) 제공된 자료에 없어서 운영 시간·출입구·이동 시간·음식 정보를 확인할 수 없어요. 확인되지 않은 정보로 코스를 만들지 않았어요.\n방문 전에 공식 안내에서 당일 운영 시간, 휴무일, 출입 제한, 음식 재료·알레르기 성분을 확인해 주세요.\n자료에 있는 해담 옛시장·성진정 코스가 필요하면 그렇게 요청해 주세요. 예약·발송·결제는 하지 않았어요.",
    "en": "{places} is not in the provided materials, so its opening hours, entrances, travel times and food information cannot be verified. I did not build a course from unverified information.\nBefore visiting, check the official notice for same-day hours, closures, access limits, and food ingredients and allergens.\nIf you need the Haedam Old Market and Seongjinjeong course from the materials, ask for it. Nothing was booked, sent or paid.",
    "ja": "ご依頼の{places}は提供資料にないため、営業時間・出入口・移動時間・食事の情報を確認できません。確認できない情報でコースは作成していません。\n訪問前に公式案内で当日の営業時間、休業日、通行制限、食材やアレルゲンを確認してください。\n資料にあるヘダム旧市場・ソンジンジョンのコースが必要な場合はそうご依頼ください。予約・送信・支払いは行っていません。",
    "zh-Hans": "您询问的{places}不在提供的资料中，无法确认营业时间、出入口、移动时间和饮食信息。我没有用未经确认的信息制定路线。\n出发前请通过官方公告确认当天营业时间、休息日、通行限制以及食材和过敏原。\n如需资料中的海潭旧市场和城镇亭路线，请直接提出。未进行任何预订、发送或付款。",
    "zh-Hant": "您詢問的{places}不在提供的資料中，無法確認營業時間、出入口、移動時間和飲食資訊。我沒有用未經確認的資訊制定路線。\n出發前請透過官方公告確認當天營業時間、休息日、通行限制以及食材和過敏原。\n如需資料中的海潭舊市場和城鎮亭路線，請直接提出。未進行任何預訂、發送或付款。",
}


def unlisted_places(request: str, docs: Dict[str, str]) -> List[str]:
    """요청에 나온 장소 이름 중 제공 자료(뷰티 자료 제외)에 없는 것. 자료 밖 장소로 가상 코스를 만들지 않기 위해 쓴다."""
    corpus = " ".join(text for name, text in docs.items() if not name.startswith("beauty/"))
    found = []
    for pattern in PLACE_PATTERNS:
        for match in pattern.finditer(request or ""):
            name = match.group(0).strip()
            if GENERIC_PLACE.fullmatch(name) or KNOWN_PLACE.search(name) or name in corpus or name in found:
                continue
            found.append(name)
    return found


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
    outside = unlisted_places(request, docs)
    if outside:
        text = UNLISTED_PLACE.get(language, UNLISTED_PLACE["en"]).format(places=", ".join(outside))
        localized = {"language": language, "display_names": {}, "draft": text, "recommendation_reasons": [],
                     "route_notes": [], "notices": [], "caveats": [], "status": "ok", "status_reason": None}
        return {"visit_date": visit.isoformat(), "people": [], "notices": [], "language": language,
                "localized": localized, "draft": text, "uncertain": {}, "conflicts": [],
                "culture_validation": {"replaced_fields": [], "unlisted_places": outside}}
    constraints = culture_constraints(trusted, visit, people, request, caveats,
                                      current_people_csv=docs.get("people/contacts_current.csv", ""))
    archive = docs.get("people/same_name_archive.txt", "")
    archive_verdict = verdicts.get("people/same_name_archive.txt")
    if archive_verdict and "irrelevant" in archive_verdict.flags and "prompt_injection" not in archive_verdict.flags:
        for person in constraints["confirmed_food_people"]:
            record = re.search(rf"(?m)^{re.escape(person['name'])}\s*/\s*(20\d{{2}})\s+청소년\s+해설사\s*/\s*음식\s*제한\s*없음\.\s*현재\s*방문단과\s*무관한\s*동명이인", archive)
            if record:
                constraints["same_name_records"].append({"name": person["name"], "year": record[1]})
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
    localized, validation = guard_culture_projection(localized, constraints, notices, caveat_texts, request=request)
    return {"visit_date": visit.isoformat(), "people": people, "notices": notices,
            "language": language, "localized": localized,
            "draft": localized["draft"], "uncertain": caveats, "conflicts": conflicts,
            "culture_validation": validation}
