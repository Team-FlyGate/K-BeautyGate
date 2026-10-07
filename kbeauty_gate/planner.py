"""맞춤 판단(제품 순위)과 하루 동선 계획."""
import re
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple

from . import nvidia
from .config import Settings

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


def rank_products(products: List[Dict], profile: Dict, settings: Settings) -> Tuple[List[Dict], List[Dict]]:
    """신뢰 통과한 제품만 받아 피부·고민·회피 성분·드라마 요청으로 점수를 매긴다."""
    ranked, excluded = [], []
    request = profile.get("request", "")
    wants_drama = bool(re.search(r"드라마|ドラマ|drama|剧", request, flags=re.IGNORECASE))

    for p in products:
        if profile.get("avoid_ingredients") and not p.get("ingredients_verified", False):
            excluded.append({"product": p["name"], "reason": "전성분표가 확인되지 않아 회피 성분 여부 확인 필요"})
            continue
        hit = _avoided(p, profile.get("avoid_ingredients", []))
        if hit:
            excluded.append({"product": p["name"], "reason": f"피하고 싶은 성분 포함: {hit}"})
            continue
        score, why = 0.0, []
        if profile.get("skin_type") in p["skin_types"]:
            score += 2
            why.append(f"{profile['skin_type']} 피부 적합")
        elif "all" in p["skin_types"]:
            score += 1
        overlap = set(profile.get("concerns", [])) & set(p["concerns"])
        if overlap:
            score += 1.5 * len(overlap)
            why.append("고민 해결: " + ", ".join(sorted(overlap)))
        if wants_drama and p.get("drama_ref"):
            score += 2
            why.append(p["drama_ref"])
        ranked.append({"product": p, "score": score, "why": why})

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
