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
from .language import detect_language, localized_projection, normalize_locale
from .trust import Verdict

NEED_KO = {
    "vegan": "저는 비건이에요. 고기, 생선, 멸치 육수, 젓갈은 빼 주세요.",
    "peanut allergy": "땅콩 알레르기가 있어요.",
    "sesame allergy": "참깨 알레르기가 있어요. 들깨는 다른 재료지만, 들어갔는지 알려 주세요.",
    "wheelchair": "휠체어를 이용해요. 계단 없는 길이나 경사로를 알려 주세요.",
}


def _date_tokens(d: date) -> List[str]:
    return [d.isoformat(), f"{d.month}월 {d.day}일"]


def _applicable(docs: Dict[str, str], verdicts: Dict[str, Verdict], visit: date) -> List[str]:
    """방문일을 언급하는 믿을 만한 공지 문장만 뽑는다."""
    tokens = _date_tokens(visit)
    out = []
    for name, text in docs.items():
        v = verdicts.get(name)
        if not v or not v.trusted or name.startswith("beauty/"):
            continue
        for sentence in re.split(r"(?<=[.다])\s+", text):
            if any(t in sentence for t in tokens):
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


def run_culture(docs: Dict[str, str], verdicts: Dict[str, Verdict], request: str, settings, language=None) -> Dict:
    group = json.loads(docs.get("travel/visitor_group.json", "{}") or "{}")
    visit = date.fromisoformat(group.get("date", date.today().isoformat()))
    people = people_from(docs)
    notices = _applicable(docs, verdicts, visit)
    trusted = {n: t for n, t in docs.items()
               if not n.startswith("beauty/") and n in verdicts and verdicts[n].trusted}
    caveats = {n: classify_sentences(docs[n]) for n in trusted if "uncertain" in verdicts[n].flags}
    conflicts = find_conflicts(docs, verdicts)
    language = normalize_locale(language) if language else detect_language(request)

    facts = {
        "request": request,
        "visit_date": visit.isoformat(),
        "approval": group.get("approval", "draft_only"),
        "people": people,
        "notices_for_visit_date": notices,
        "trusted_sources": {source_label(n): t for n, t in trusted.items()},
        "statements_by_certainty": {source_label(n): items for n, items in caveats.items()},
        "excluded_due_to_conflict": conflicts,
    }
    localized = localized_projection(
        settings, language, "culture", facts, notices=notices,
        caveats=[f"[{item['certainty']}] {item['sentence']}" for items in caveats.values() for item in items] + conflicts,
        proper_names=[p["name"] for p in people] + ["해담 옛시장", "해담", "성진정"],
    )
    return {"visit_date": visit.isoformat(), "people": people, "notices": notices,
            "language": language, "localized": localized,
            "draft": localized["draft"], "uncertain": caveats, "conflicts": conflicts}
