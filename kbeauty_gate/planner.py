"""맞춤 판단(제품 순위)과 하루 동선 계획."""
import re
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple

from . import nvidia, regulatory
from .config import Settings

SKIN_KO = {"combination": "복합성", "dry": "건성", "oily": "지성", "sensitive": "민감성", "normal": "중성"}
CONCERN_KO = {"redness": "붉어짐", "dryness": "건조함", "dullness": "칙칙함", "pores": "모공", "color": "색조"}
STORE_MIN = 40      # 매장 한 곳에 머무는 시간(분)
SAME_AREA_MOVE = 10
OTHER_AREA_MOVE = 35


def hm(text: str) -> int:
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _avoided(product: Dict, avoid: List[str]) -> Optional[str]:
    for word in avoid:
        for ing in product.get("ingredients", []):
            if word.lower() in ing.lower():
                return ing
    return None


# 요청 문장에서 제품 종류와 목적을 읽는다 (예: "진정 토너" → 토너만, 고민에 붉어짐 추가)
CATEGORY_WORDS = {
    "toner": r"토너|스킨|toner|トナー|化粧水|爽肤水|化妝水",
    "cream": r"크림|cream|クリーム|面霜|乳霜",
    "sunscreen": r"선크림|썬크림|선블록|자외선\s*차단|sunscreen|sunblock|spf|日焼け止め|防晒|防曬",
    "mask": r"마스크\s*팩|시트\s*마스크|마스크팩|팩|sheet\s*mask|face\s*mask|マスク|パック|面膜",
    "lip": r"립|lip|リップ|口红|口紅|唇",
    "cushion": r"쿠션|cushion|クッション|气垫|氣墊",
    "essence": r"에센스|essence|エッセンス|精华液|精華液",
    "serum": r"세럼|앰플|serum|ampoule|美容液|精华|精華",
    "gel": r"젤|gel|ジェル|凝胶|凝膠",
}
PURPOSE_WORDS = {
    "redness": r"진정|붉|calm|sooth|redness|鎮静|赤み|镇静|鎮靜|泛红|泛紅",
    "dryness": r"보습|수분|건조|moistur|hydrat|dry|保湿|乾燥|补水|補水",
    "pores": r"모공|pore|毛穴|毛孔",
    "dullness": r"미백|톤\s*업|칙칙|bright|dull|美白|くすみ|提亮",
}


def request_preferences(request: str) -> Tuple[set, set]:
    cats = {c for c, pat in CATEGORY_WORDS.items() if re.search(pat, request or "", re.IGNORECASE)}
    purposes = {c for c, pat in PURPOSE_WORDS.items() if re.search(pat, request or "", re.IGNORECASE)}
    return cats, purposes


def rank_products(products: List[Dict], profile: Dict, settings: Settings) -> Tuple[List[Dict], List[Dict]]:
    """신뢰 통과한 제품만 받아 피부·고민·회피 성분·드라마 요청으로 점수를 매긴다."""
    ranked, excluded = [], []
    request = profile.get("request", "")
    wants_drama = bool(re.search(r"드라마|ドラマ|drama|剧", request, flags=re.IGNORECASE))
    # 따옴표 속 제품명·정품 확인 대상(예: "Miracle Essence")은 '원하는 종류'로 읽지 않는다
    plain = re.sub(r"[「『\"“'‘][^」』\"”'’]*[」』\"”'’]", " ", request)
    for item in profile.get("check_items") or []:
        plain = plain.replace(item, " ")
    wanted_cats, purposes = request_preferences(plain)
    if purposes - set(profile.get("concerns") or []):
        profile = {**profile, "concerns": sorted(set(profile.get("concerns") or []) | purposes)}
    # 요청한 종류가 후보에 있을 때만 종류로 거른다 (없으면 거르지 않고 그대로 추천)
    if wanted_cats and not any(p.get("category") in wanted_cats for p in products):
        wanted_cats = set()

    for p in products:
        if wanted_cats and p.get("category") not in wanted_cats:
            excluded.append({"product": p["name"], "reason": "요청한 제품 종류가 아님"})
            continue
        if profile.get("avoid_ingredients") and not p.get("ingredients_verified", False):
            excluded.append({"product": p["name"], "reason": "전성분표가 확인되지 않아 회피 성분 여부 확인 필요"})
            continue
        hit = _avoided(p, profile.get("avoid_ingredients", []))
        if hit:
            excluded.append({"product": p["name"], "reason": f"피하고 싶은 성분 포함: {hit}"})
            continue
        score, why = 0.0, []
        skin = profile.get("skin_type")
        if skin in p["skin_types"]:
            score += 2
            why.append(f"{SKIN_KO.get(skin, skin)} 피부에 맞는 제품")
        elif "all" in p["skin_types"]:
            score += 1
            why.append("피부 타입에 관계없이 쓰는 제품")
        overlap = set(profile.get("concerns", [])) & set(p["concerns"])
        if overlap:
            score += 1.5 * len(overlap)
            why.append("고민(" + ", ".join(CONCERN_KO.get(c, c) for c in sorted(overlap)) + ")에 도움")
        if wants_drama and p.get("drama_ref"):
            score += 2
            why.append(p["drama_ref"])
        # 고민을 말했으면 그 고민과 맞는 제품만, 아니면 피부 타입이 맞는 제품만 추천한다
        concerns = profile.get("concerns") or []
        if wanted_cats:  # 종류를 콕 집어 말했으면 그 종류 안에서는 고민이 덜 맞아도 후보로 둔다
            relevant = True
        elif concerns:
            relevant = bool(overlap)
        elif skin:
            relevant = skin in p["skin_types"]
        else:  # 피부 정보를 말하지 않았으면 걸러 내지 않는다
            relevant = True
        if not relevant and not (wants_drama and p.get("drama_ref")):
            excluded.append({"product": p["name"], "reason": "말씀하신 피부 고민과 관련이 적음"})
            continue
        if profile.get("avoid_ingredients"):
            why.append("피하고 싶은 성분이 전성분표에 없음")
        if p.get("ingredients_verified"):
            # 공식 규제 데이터 대조: 식약처(나라별 금지·제한) 우선, 대만 TFDA는 금지 목록만 보조로
            kr_hits = regulatory.check_kr(p["ingredients"])
            tw = regulatory.check(p["ingredients"])
            if kr_hits is not None:
                kr = regulatory.kr_reasons(kr_hits, profile.get("language", "ko"),
                                           regulatory.recalled(p.get("name_ko", ""), p.get("brand", "")))
                if kr["block"]:
                    excluded.append({"product": p["name"], "reason": kr["block"][0]})
                    continue
                why.extend(kr["info"])
            if tw and tw["prohibited"]:
                excluded.append({"product": p["name"], "reason": regulatory.reasons_ko(tw)[0]})
                continue
            if tw and kr_hits is None:
                why.extend(regulatory.reasons_ko(tw))
        ranked.append({"product": p, "score": score, "why": why, "fits_concern": bool(overlap)})

    query = f"{profile.get('skin_type')} skin, concerns {profile.get('concerns')}; {request}"
    passages = [f"{r['product']['name']} ({r['product']['category']}): "
                f"{', '.join(r['product']['ingredients'])}; for {', '.join(r['product']['skin_types'])}"
                for r in ranked]
    sims = nvidia.relevance(settings, query, passages)
    if sims:
        lo, hi = min(sims), max(sims)
        for r, sim in zip(ranked, sims):
            r["relevance"] = round((sim - lo) / (hi - lo + 1e-9), 3)
            r["score"] += 2 * r["relevance"]

    # 종류를 말했고 그 종류 안에 고민(목적)까지 맞는 제품이 있으면 그것만 남긴다 ("진정 토너" → 모공 토너 제외)
    if wanted_cats and (profile.get("concerns")) and any(r["fits_concern"] for r in ranked):
        for r in [r for r in ranked if not r["fits_concern"]]:
            excluded.append({"product": r["product"]["name"], "reason": "요청한 목적과 맞지 않음"})
        ranked = [r for r in ranked if r["fits_concern"]]
    ranked.sort(key=lambda r: -r["score"])
    picked, total = [], 0
    for r in ranked:
        if len(picked) == 5:
            break
        price = r["product"]["price_krw"]
        if total + price <= profile.get("budget_krw", 10 ** 9):
            picked.append(r)
            total += price
    return picked, excluded


def apply_notices(stores: List[Dict], notices: List[Tuple[str, str]], visit: date) -> List[str]:
    """신뢰 통과한 공지만 적용해 방문일 영업시간을 고친다."""
    applied = []
    day = visit.isoformat()
    for source, text in notices:
        for line in text.splitlines():
            if day not in line:
                continue
            for s in stores:
                if s["name_ko"] in line:
                    m = re.search(r"(\d{2}:\d{2})\s*조기\s*마감", line)
                    if m:
                        open_t = s["hours"].split("-")[0]
                        s["hours_today"] = f"{open_t}-{m.group(1)}"
                        applied.append(f"{s['name_ko']}: {day} {m.group(1)} 조기 마감 ({source})")
                    elif "휴무" in line:
                        s["closed_today"] = True
                        applied.append(f"{s['name_ko']}: {day} 휴무 ({source})")
    return applied


@dataclass
class Stop:
    start: int
    end: int
    kind: str
    name: str
    area: str
    note: str


def plan_route(picked: List[Dict], stores: List[Dict], experiences: List[Dict], profile: Dict) -> Tuple[List[Stop], List[str]]:
    win_start, win_end = (hm(t) for t in profile["time_window"].split("-"))
    areas = profile.get("areas", [])
    skipped: List[str] = []

    need = {r["product"]["id"] for r in picked}
    chosen: List[Dict] = []
    open_stores = [s for s in stores if not s.get("closed_today")]
    while need:
        best = max(open_stores, key=lambda s: (len(need & set(s["carries"])), s["area"] in areas), default=None)
        if not best or not need & set(best["carries"]):
            break
        chosen.append(best)
        need -= set(best["carries"])
        open_stores.remove(best)

    stops = [{"kind": "store", "name": s["name_ko"], "area": s["area"],
              "hours": s.get("hours_today", s["hours"]), "minutes": STORE_MIN,
              "note": "구매: " + ", ".join(r["product"]["name_ko"] for r in picked if r["product"]["id"] in s["carries"])}
             for s in chosen]
    for e in experiences:
        stops.append({"kind": "experience", "name": e["name"], "area": e["area"], "hours": e["hours"],
                      "minutes": e["minutes"], "note": e["note"]})

    def area_rank(a: str) -> int:
        return areas.index(a) if a in areas else len(areas)

    stops.sort(key=lambda s: (area_rank(s["area"]), hm(s["hours"].split("-")[1])))

    route, clock, here = [], win_start, None
    for s in stops:
        if here is not None:
            clock += SAME_AREA_MOVE if s["area"] == here else OTHER_AREA_MOVE
        open_t, close_t = (hm(t) for t in s["hours"].split("-"))
        start = max(clock, open_t)
        end = start + s["minutes"]
        if end > close_t or end > win_end:
            skipped.append(f"{s['name']}: 영업({s['hours']}) 또는 일정 시간 안에 들를 수 없음")
            continue
        route.append(Stop(start, end, s["kind"], s["name"], s["area"], s["note"]))
        clock, here = end, s["area"]
    return route, skipped
