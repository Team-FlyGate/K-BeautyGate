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
from .culture import food_card, run_culture
from .guard import AuditLog, SafeFS
from .language import COPY, LANG_NAME, detect_language, in_language, localized_projection, normalize_locale
from .planner import apply_notices, fmt, plan_route, rank_products
from .trust import assess_product

BEAUTY_WORDS = re.compile(r"화장품|뷰티|코스메|beauty|cosmetic|skincare|コスメ|化妆品|美妆", re.IGNORECASE)
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
        mode = "beauty" if (profile and profile.get("skin_type")) or BEAUTY_WORDS.search(request) else "culture"
    profile = dict(profile or {})
    language = detect_language(request, previous=profile.get("language"), default=normalize_locale(profile.get("language")))
    profile["language"] = language
    if mode == "culture":
        try:
            group_text = fs.read_text(input_dir / "travel" / "visitor_group.json")
        except FileNotFoundError:
            group_text = None
        group = json.loads(group_text or "{}")
        visit = date.fromisoformat(group.get("date", date.today().isoformat()))
    else:
        visit = date.fromisoformat(profile["visit_date"]) if profile.get("visit_date") else date.today()

    # 1) 수집 + 2) 신뢰성 판단 (뷰티·공통 테스트가 같은 하네스를 쓴다)
    in_scope = (lambda n: n.startswith("beauty")) if mode == "beauty" else (lambda n: not n.startswith("beauty"))
    docs, doc_verdicts = collect(fs, input_dir, visit, in_scope)

    if mode == "culture":
        result = run_culture(docs, doc_verdicts, request, settings, language=language)
        result["mode"] = "culture"
        result["trust"] = {"documents": [v.to_dict() for v in doc_verdicts.values()]}
        fs.write_text("culture_course.md", render_culture(result))
        result["food_cards"] = "\n".join(food_card(p) for p in result["people"])
        fs.write_text("culture_food_cards_ko.md", result["food_cards"])
        result["blocked"] = [e for e in audit.events if e["decision"] == "DENIED"]
        result["saved"] = fs.saved + [str(output_dir / "trust_report.json"), str(output_dir / "audit.jsonl")]
        fs.write_text("trust_report.json", json.dumps(result, ensure_ascii=False, indent=2))
        audit.write(output_dir / "audit.jsonl")
        return result
    return run_beauty(fs, audit, docs, doc_verdicts, profile or {}, visit, settings, output_dir)


def run_beauty(fs, audit, docs, doc_verdicts, profile, visit, settings, output_dir) -> Dict:
    profile = dict(profile)
    profile["language"] = normalize_locale(profile.get("language"))
    registry = {r["brand"]: r for r in csv.DictReader(io.StringIO(docs["beauty/brands/kr_brand_registry.csv"]))}
    products = json.loads(docs["beauty/products/products.json"])
    stores = json.loads(docs["beauty/stores/stores.json"])
    product_verdicts = {p["id"]: assess_product(p, registry) for p in products}
    trusted_products = [p for p in products if product_verdicts[p["id"]].trusted]

    checks = []
    for item in profile.get("check_items", []):
        match = next((p for p in products if p["name"].lower() == item.lower()), None)
        checks.append(product_verdicts[match["id"]].to_dict() if match
                      else {"target": item, "trusted": False, "reasons": ["자료에 없는 제품이라 판단 보류"]})

    # 3) 맞춤 판단
    picked, excluded = rank_products(trusted_products, profile, settings)

    # 4) 동선: 믿을 수 있는 공지와 체험만 반영
    notices = [(n, t) for n, t in docs.items() if n.startswith("beauty/stores/") and n.endswith(".txt")
               and doc_verdicts[n].trusted]
    applied = apply_notices(stores, notices, visit)
    experiences = [_experience_from(n, t, visit) for n, t in docs.items()
                   if n.startswith("beauty/events/") and doc_verdicts[n].trusted]
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
        "trust": {"documents": [v.to_dict() for v in doc_verdicts.values()],
                  "products": [v.to_dict() for v in product_verdicts.values()]},
    }

    # 5) 결과물 저장 (output에만)
    fs.write_text("beauty_plan.md", render_plan(result, profile, settings))
    result["staff_card"] = render_card(result, profile)
    fs.write_text("beauty_staff_card_ko.md", result["staff_card"])
    result["blocked"] = [e for e in audit.events if e["decision"] == "DENIED"]
    result["saved"] = fs.saved + [str(output_dir / "trust_report.json"), str(output_dir / "audit.jsonl")]
    fs.write_text("trust_report.json", json.dumps(result, ensure_ascii=False, indent=2))
    audit.write(output_dir / "audit.jsonl")
    return result


def _in_language(text: str, lang: str) -> bool:
    return in_language(text, lang)


def render_card(result: Dict, profile: Dict) -> str:
    skin = SKIN_KO.get(profile["skin_type"], profile["skin_type"])
    concerns = "·".join(CONCERN_KO.get(c, c) for c in profile["concerns"])
    avoid = "·".join(INGREDIENT_KO.get(a, a) for a in profile["avoid_ingredients"])
    lines = [
        "# 매장 직원에게 보여주세요",
        "",
        f"안녕하세요. 저는 **{skin} 피부**이고 **{concerns}**이 고민이에요.",
        f"**{avoid}**이 들어간 제품은 피하고 싶어요.",
        "",
        "아래 제품이 있나요? 없다면 비슷한 제품을 추천해 주세요.",
        "",
    ]
    lines += [f"- {r['name_ko']} ({r['price_krw']:,}원)" for r in result["recommendations"]]
    lines += ["", "면세(Tax Free) 가능한가요? 감사합니다!"]
    return "\n".join(lines) + "\n"


def render_plan(result: Dict, profile: Dict, settings) -> str:
    language = normalize_locale(profile.get("language"))
    copy = COPY[language]
    localized = result.get("localized")
    if not localized or localized.get("language") != language:
        facts = {k: result[k] for k in ("recommendations", "route", "authenticity_checks")}
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
    result["language"] = language
    result["localized"] = localized
    result["summary"] = localized["summary"]
    result["nvidia"]["chat_model"] = settings.chat_model
    out = [f"# K-BeautyGate {copy['title']} · {profile['visit_date']}", "", localized["summary"], ""]
    out += [f"## {copy['products']}", "", f"| {copy['rank']} | {copy['product']} | {copy['price']} | {copy['why']} |", "| --- | --- | --- | --- |"]
    for index, r in enumerate(result["recommendations"]):
        out.append(f"| {r['rank']} | {r['name_ko']} | KRW {r['price_krw']:,} | {'; '.join(localized['recommendation_reasons'][index]) or '-'} |")
    out += ["", f"## {copy['route_title']}", "", f"| {copy['time']} | {copy['place']} | {copy['area']} | {copy['activity']} |", "| --- | --- | --- | --- |"]
    for index, stop in enumerate(result["route"]):
        out.append(f"| {stop['time']} | {stop['name']} | {stop['area']} | {localized['route_notes'][index]} |")
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
