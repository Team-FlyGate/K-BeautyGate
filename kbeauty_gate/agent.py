"""K-BeautyGate 에이전트: 수집 → 신뢰성 판단 → 맞춤 판단 → 동선·한글 카드 생성."""
import csv
import io
import json
import re
from datetime import date
from pathlib import Path
from typing import Dict, Optional

from . import nvidia
from .collect import collect
from .config import get_settings
from .conversation import BEAUTY_WORDS, select_mode
from .culture import culture_visit_date, food_card, run_culture
from . import jev
from .fact_guard import BEAUTY_FIX, check_beauty
from .followups import suggest
from .guard import AuditLog, SafeFS
from .request_guard import refusal_answer, screen_request
from .language import explicit_language, COPY, LANG_NAME, detect_language, display_name, in_language, localized_projection, normalize_locale
from .planner import apply_notices, fmt, plan_route, rank_products
from .trust import assess_product, assess_unlisted

AREAS = ("성수", "명동", "홍대")
SKIN_KO = {"combination": "복합성", "dry": "건성", "oily": "지성", "sensitive": "민감성", "normal": "중성"}
CONCERN_KO = {"redness": "붉어짐", "dryness": "건조함", "dullness": "칙칙함", "pores": "모공"}
INGREDIENT_KO = {"fragrance": "향료", "alcohol": "알코올"}


def _experience_from(name: str, text: str, visit: date) -> Dict:
    title = next((l.lstrip("# ").strip() for l in text.splitlines() if l.startswith("#")), name)
    area = next((a for a in AREAS if a in text), "")
    m = re.search(r"(\d{2}:\d{2})\s*~\s*(\d{2}:\d{2})", text)
    hours = f"{m.group(1)}-{m.group(2)}" if m else "11:00-21:00"
    mins = re.search(r"약\s*(\d+)\s*분", text)
    return {"name": title, "area": area, "hours": hours,
            "minutes": int(mins.group(1)) if mins else 30, "note": "체험"}


def run(input_dir: Path, output_dir: Path, profile: Optional[Dict], request: str, mode: str = "auto") -> Dict:
    input_dir, output_dir = input_dir.resolve(), output_dir.resolve()
    settings = get_settings()
    audit = AuditLog()
    fs = SafeFS(input_dir, output_dir, audit)
    if mode == "auto":
        mode = select_mode(request, profile)
    profile = dict(profile or {})
    language = detect_language(request, previous=profile.get("language"), default=normalize_locale(profile.get("language")))
    # 화면에서 직접 고른 언어가 있으면 그 언어로 답한다. 문장 안의 명시적 요청("일본어로 답해 줘")만 이보다 우선한다.
    if profile.get("preferred_language") and not explicit_language(request):
        language = normalize_locale(profile["preferred_language"])
    profile["language"] = language
    # 0) 사용자 요청 자체를 먼저 본다 (금지 구역, 비밀, 발송, 예약, 자료 속 지시)
    refusals = screen_request(request)
    # 비자기회귀(Non-autoregressive) 판단 모델 게이트: 규칙이 놓친 위험 요청(예: "카톡으로 공유해 줘")을 확률로 한 번 더 본다
    jev_req = jev.check_request(request)
    if jev_req:
        audit.record("judge-request", jev_req["kind"], "SCORED", f"비자기회귀 판단 모델 위험 요청 확률 {jev_req['p']:.2f} ({jev_req['model']})")
        action = jev.ACTION_FOR.get(jev_req["kind"])
        if action and jev_req["p"] >= 0.7 and action not in {r["action"] for r in refusals}:
            refusals.append({"action": action, "reason": f"비자기회귀 판단 모델: 위험 요청 확률 {jev_req['p']:.2f}"})
    for item in refusals:
        audit.record("user-request", item["action"], "DENIED", item["reason"])
    if mode == "culture":
        try:
            group_text = fs.read_text(input_dir / "travel" / "visitor_group.json")
        except FileNotFoundError:
            group_text = None
        group = json.loads(group_text or "{}")
        visit = culture_visit_date(request, group.get("date", date.today().isoformat()))
    else:
        visit = date.fromisoformat(profile["visit_date"]) if profile.get("visit_date") else date.today()

    # 1) 수집 + 2) 신뢰성 판단 (뷰티·공통 테스트가 같은 하네스를 쓴다)
    in_scope = (lambda n: n.startswith("beauty")) if mode == "beauty" else (lambda n: not n.startswith("beauty"))
    docs, doc_verdicts = collect(fs, input_dir, visit, in_scope)

    if mode == "culture":
        result = run_culture(docs, doc_verdicts, request, settings, language=language)
        result["refusals"] = refusals
        answer = refusal_answer(refusals, language)
        if answer:
            result["localized"] = {**result["localized"], "draft": answer}
            result["draft"] = result["localized"]["draft"]
        result["mode"] = "culture"
        result["trust"] = {"documents": [v.to_dict() for v in doc_verdicts.values()]}
        fs.write_text("culture_course.md", render_culture(result))
        result["food_cards"] = "\n".join(food_card(p) for p in result["people"])
        fs.write_text("culture_food_cards_ko.md", result["food_cards"])
        result["suggestions"] = suggest(settings, result, profile, "culture")
        result["blocked"] = [e for e in audit.events if e["decision"] == "DENIED"]
        result["saved"] = fs.saved + [str(output_dir / "trust_report.json"), str(output_dir / "audit.jsonl")]
        fs.write_text("trust_report.json", json.dumps(result, ensure_ascii=False, indent=2))
        audit.write(output_dir / "audit.jsonl")
        return result
    return run_beauty(fs, audit, docs, doc_verdicts, profile or {}, visit, settings, output_dir, refusals)


def run_beauty(fs, audit, docs, doc_verdicts, profile, visit, settings, output_dir, refusals=()) -> Dict:
    profile = dict(profile)
    profile["language"] = normalize_locale(profile.get("language"))
    registry = {r["brand"]: r for r in csv.DictReader(io.StringIO(docs["beauty/brands/kr_brand_registry.csv"]))}
    products = json.loads(docs["beauty/products/products.json"])
    stores = json.loads(docs["beauty/stores/stores.json"])
    product_verdicts = {p["id"]: assess_product(p, registry) for p in products}
    trusted_products = [p for p in products if product_verdicts[p["id"]].trusted]

    checks = []
    for item in profile.get("check_items", []):
        match = _find_product(products, item)
        checks.append(product_verdicts[match["id"]].to_dict() if match
                      else assess_unlisted(item))

    # 3) 맞춤 판단
    # 사용자가 고른 지역의 매장에서 살 수 있는 제품만 추천한다
    areas = profile.get("areas") or []
    if areas:
        in_area = {pid for st in stores if st["area"] in areas for pid in st["carries"]}
        trusted_products = [p for p in trusted_products if p["id"] in in_area]
    picked, excluded = rank_products(trusted_products, profile, settings)

    # 4) 동선: 믿을 수 있는 공지와 체험만 반영
    notices = [(n, t) for n, t in docs.items() if n.startswith("beauty/stores/") and n.endswith(".txt")
               and doc_verdicts[n].trusted]
    applied = apply_notices(stores, notices, visit)
    experiences = [_experience_from(n, t, visit) for n, t in docs.items()
                   if n.startswith("beauty/events/") and doc_verdicts[n].trusted]
    if areas:
        experiences = [e for e in experiences if e["area"] in areas]
        stores = [st for st in stores if st["area"] in areas]
    route, skipped = plan_route(picked, stores, experiences, profile)

    result = {
        "mode": "beauty",
        "language": normalize_locale(profile.get("language")),
        "profile": {k: v for k, v in profile.items() if k != "name"},
        "nvidia": {"online": settings.online, "chat_model": settings.chat_model,
                   "embed_model": settings.embed_model,
                   "embedding_used": any("relevance" in r for r in picked)},
        "recommendations": [{"rank": i + 1, "id": r["product"]["id"], "name": r["product"]["name"],
                             "name_ko": r["product"]["name_ko"], "price_krw": r["product"]["price_krw"],
                             "why": r["why"], "score": round(r["score"], 2)} for i, r in enumerate(picked)],
        "excluded_by_profile": excluded,
        "route": [{"time": f"{fmt(s.start)}-{fmt(s.end)}", "kind": s.kind, "name": s.name,
                   "area": s.area, "note": s.note} for s in route],
        "route_skipped": skipped,
        "notices_applied": applied,
        "authenticity_checks": checks,
        "refusals": list(refusals),
        "trust": {"documents": [v.to_dict() for v in doc_verdicts.values()],
                  "products": [v.to_dict() for v in product_verdicts.values()]},
    }

    # 5) 결과물 저장 (output에만)
    fs.write_text("beauty_plan.md", render_plan(result, profile, settings))
    result["staff_card"] = render_card(result, profile)
    fs.write_text("beauty_staff_card_ko.md", result["staff_card"])
    result["suggestions"] = suggest(settings, result, profile, "beauty")
    result["blocked"] = [e for e in audit.events if e["decision"] == "DENIED"]
    result["saved"] = fs.saved + [str(output_dir / "trust_report.json"), str(output_dir / "audit.jsonl")]
    fs.write_text("trust_report.json", json.dumps(result, ensure_ascii=False, indent=2))
    audit.write(output_dir / "audit.jsonl")
    return result


def _in_language(text: str, lang: str) -> bool:
    return in_language(text, lang)


def _find_product(products, item: str):
    """정품 확인 대상 찾기: 완전 일치가 없으면 이름의 단어가 2개 이상 겹치는 제품 (예: "Seoul Glow Snail 에센스")."""
    key = re.sub(r"\s+", " ", item or "").strip().lower()
    for p in products:
        if key in (p["name"].lower(), p.get("name_ko", "").lower()):
            return p
    words = {w for w in re.split(r"[\s.()\[\]·,_%-]+", key) if len(w) >= 3}
    best, best_hits = None, 1
    for p in products:
        name = f"{p['name']} {p.get('name_ko', '')} {p.get('brand', '')}".lower()
        hits = sum(1 for w in words if w in name)
        if hits > best_hits:
            best, best_hits = p, hits
    return best


def render_card(result: Dict, profile: Dict) -> str:
    """매장 직원용 한글 카드. 사용자가 말한 정보만 넣는다."""
    skin = profile.get("skin_type")
    concerns = "·".join(CONCERN_KO.get(c, c) for c in profile.get("concerns") or [])
    avoid = "·".join(INGREDIENT_KO.get(a, a) for a in profile.get("avoid_ingredients") or [])
    intro = "안녕하세요."
    if skin:
        intro += f" 저는 **{SKIN_KO.get(skin, skin)} 피부**예요."
    if concerns:
        intro += f" **{concerns}**이(가) 고민이에요."
    lines = ["# 매장 직원에게 보여주세요", "", intro]
    if avoid:
        lines.append(f"**{avoid}**이(가) 들어간 제품은 피하고 싶어요.")
    lines += ["", "아래 제품이 있나요? 없다면 비슷한 제품을 추천해 주세요.", ""]
    lines += [f"- {r['name_ko']} ({r['price_krw']:,}원)" for r in result["recommendations"]]
    lines += ["", "면세(Tax Free) 가능한가요? 감사합니다!"]
    return "\n".join(lines) + "\n"


def render_plan(result: Dict, profile: Dict, settings) -> str:
    language = normalize_locale(profile.get("language"))
    copy = COPY[language]
    localized = result.get("localized")
    if not localized or localized.get("language") != language or "display_names" not in localized:
        facts = {k: result[k] for k in ("recommendations", "route", "authenticity_checks")}
        facts["profile"] = {key: profile.get(key) for key in ("skin_type", "concerns", "avoid_ingredients", "areas")}
        names = [name for r in result["recommendations"] for name in (r["name"], r["name_ko"])]
        names += [name for stop in result["route"] for name in (stop["name"], stop["area"])]
        names += [check["target"] for check in result["authenticity_checks"]]
        localized = localized_projection(
            settings, language, "beauty", facts,
            reasons=[r["why"] for r in result["recommendations"]],
            route_notes=[stop["note"] for stop in result["route"]],
            notices=result["notices_applied"], caveats=result.get("route_skipped", []),
            proper_names=names,
        )
    # "금지 성분 없음"을 "안전한 제품·기준 충족"으로 부풀린 문장은 사실 문장으로 바꾼다
    summary_fixed, safety_hits = check_beauty(localized.get("summary", ""), language)
    reasons_fixed = []
    for row in localized.get("recommendation_reasons") or []:
        fixed_row = []
        for item in row:
            fixed_item, item_hits = check_beauty(item, language)
            safety_hits += item_hits
            fixed_row.append(BEAUTY_FIX[language if language in BEAUTY_FIX else "en"] if item_hits else fixed_item)
        reasons_fixed.append(fixed_row)
    if safety_hits:
        localized = {**localized, "summary": summary_fixed, "recommendation_reasons": reasons_fixed}
        result["fact_guard"] = safety_hits
    answer = refusal_answer(result.get("refusals") or [], language)
    if answer:
        localized = {**localized, "summary": answer}
    result["language"] = language
    result["localized"] = localized
    result["summary"] = localized["summary"]
    result["nvidia"]["chat_model"] = settings.chat_model
    out = [f"# K-BeautyGate {copy['title']} · {profile['visit_date']}", "", localized["summary"], ""]
    out += [f"## {copy['products']}", "", f"| {copy['rank']} | {copy['product']} | {copy['price']} | {copy['why']} |", "| --- | --- | --- | --- |"]
    for index, r in enumerate(result["recommendations"]):
        out.append(f"| {r['rank']} | {display_name(r['name_ko'], localized, language)} | KRW {r['price_krw']:,} | {'; '.join(localized['recommendation_reasons'][index]) or '-'} |")
    out += ["", f"## {copy['route_title']}", "", f"| {copy['time']} | {copy['place']} | {copy['area']} | {copy['activity']} |", "| --- | --- | --- | --- |"]
    for index, stop in enumerate(result["route"]):
        out.append(f"| {stop['time']} | {display_name(stop['name'], localized, language)} | {display_name(stop['area'], localized, language)} | {localized['route_notes'][index]} |")
    if localized["notices"]:
        out += ["", f"## {copy['notices']}", ""] + [f"- {item}" for item in localized["notices"]]
    if localized["caveats"]:
        out += ["", f"## {copy['caveats']}", ""] + [f"- {item}" for item in localized["caveats"]]
    out += ["", f"## {copy['sources']}", ""]
    for d in result["trust"]["documents"] + result["trust"]["products"]:
        if not d["trusted"] and (d in result["trust"]["products"] or d["target"].startswith("beauty/")):
            out.append(f"- **{d['target']}** ({', '.join(d['flags'])}): {' / '.join(d['reasons'])}")
    for e in result["excluded_by_profile"]:
        out.append(f"- **{e['product']}**: {e['reason']}")
    if result["authenticity_checks"]:
        out += ["", "## 정품 확인 요청", ""]
        for c in result["authenticity_checks"]:
            verdict = "한국 브랜드 정품으로 확인" if c["trusted"] else "위장 K-뷰티 의심, 구매 비추천"
            out.append(f"- **{c['target']}**: {verdict} ({' / '.join(c['reasons'])})")

    return "\n".join(out) + "\n"


def render_culture(result: Dict) -> str:
    language = normalize_locale(result.get("language"), "ko")
    copy = COPY[language]
    localized = result.get("localized", {})
    out = [f"# {copy['culture']} · {result['visit_date']}", "", copy["draft_only"], "", result["draft"], ""]
    if localized.get("notices"):
        out += [f"## {copy['notices']}", ""] + [f"- {item}" for item in localized["notices"]] + [""]
    if localized.get("caveats"):
        out += [f"## {copy['caveats']}", ""] + [f"- {item}" for item in localized["caveats"]] + [""]
    out += [f"## {copy['sources']}", ""]
    if result["uncertain"]:
        out += ["## 근거 확실성 (문장별)", ""]
        for n, items in result["uncertain"].items():
            out += [f"**{n}**"] + [f"- [{i['certainty']}] {i['sentence']}" for i in items] + [""]
    if result.get("conflicts"):
        out += ["## 충돌로 제외", ""] + [f"- {c}" for c in result["conflicts"]] + [""]
    out += ["## 걸러낸 자료", ""]
    for d in result["trust"]["documents"]:
        if not d["trusted"] and not d["target"].startswith("beauty/"):
            out.append(f"- **{d['target']}** ({', '.join(d['flags'])}): {' / '.join(d['reasons'])}")
    return "\n".join(out) + "\n"
