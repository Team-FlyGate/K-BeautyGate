"""공식 규제 데이터와 제품 전성분 대조.

- 한국 식약처 화장품 규제정보·회수 목록 스냅샷 (beauty/regulatory/kr_mfds/) — 나라별 금지·제한 국가 포함
- 대만 TFDA 공개 CSV (beauty/regulatory/tw_tfda/) — 금지·사용 제한·자외선 차단제 한도
수집 단계(collect)가 SafeFS로 읽은 파일 내용을 prime()으로 넘기고, 추천 단계(planner)가 check()로 대조한다.
실행 중 외부 호출이 없으므로 OpenShell 네트워크 정책을 바꿀 필요가 없다.
"""
import csv
import io
import json
import re
from typing import Dict, List, Optional

PREFIX = "beauty/regulatory/tw_tfda/"
KR_PREFIX = "beauty/regulatory/kr_mfds/"
# 답변 언어로 사용자의 나라 기준을 추정한다 (식약처 규제정보의 국가 표기와 같게)
COUNTRY_BY_LANG = {"ko": "한국", "ja": "일본", "zh-Hans": "중국", "zh-Hant": "대만", "en": "미국"}
_KR: Dict[str, Dict] = {}
_RECALL: List[Dict] = []
SOURCE = {"authority": "Taiwan TFDA", "authority_ko": "대만 식약서(TFDA)", "fetched": "2026-10-07"}
_LISTS: Dict[str, Dict[str, Dict]] = {}


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").replace("　", " ")).strip().lower()


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def prime(docs: Dict[str, str]) -> None:
    """collect()가 읽은 문서 중 규제 데이터만 골라 이름 → 항목 사전으로 만든다."""
    _LISTS.clear()
    _KR.clear()
    _RECALL.clear()
    try:
        for row in json.loads(docs.get(f"{KR_PREFIX}regulation.json") or "[]"):
            entry = {"std": _clean(row.get("INGR_STD_NAME") or ""), "eng": _clean(row.get("INGR_ENG_NAME") or ""),
                     "prohibited": [c for c in re.split(r"\s*,\s*", row.get("PROH_NATIONAL") or "") if c],
                     "limited": [c for c in re.split(r"\s*,\s*", row.get("LIMIT_NATIONAL") or "") if c]}
            for key in (entry["eng"], entry["std"]):
                if key:
                    _KR.setdefault(_norm(key), entry)
        _RECALL.extend(json.loads(docs.get(f"{KR_PREFIX}recall.json") or "[]"))
    except json.JSONDecodeError:
        pass
    for kind in ("prohibited", "restricted", "sunscreen"):
        text = docs.get(f"{PREFIX}{kind}.csv")
        if not text:
            continue
        table: Dict[str, Dict] = {}
        for row in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
            entry = {
                "kind": kind,
                "name": _clean(row.get("成分名") or row.get("成分名稱") or ""),
                "inci": _clean(row.get("INCI名") or ""),
                "cas": _clean(row.get("CAS_NO.") or row.get("CAS_No.") or row.get("CAS_Number") or ""),
                "limit": _clean(row.get("限量標準") or ""),
            }
            for key in (entry["name"], entry["inci"]):
                if key:
                    table.setdefault(_norm(key), entry)
                    # "Mercury and its compounds" → "mercury" 로도 찾는다
                    base = re.sub(r"\s+and its (compounds|salts|esters)$", "", _norm(key))
                    if base != _norm(key):
                        table.setdefault(base, entry)
        _LISTS[kind] = table


def available() -> bool:
    return bool(_LISTS or _KR)


def check_kr(ingredients: List[str]) -> Optional[List[Dict]]:
    """식약처 규제정보에서 성분별 금지·제한 국가를 찾는다. 데이터가 없으면 None."""
    if not _KR:
        return None
    hits = []
    for ing in ingredients or []:
        e = _KR.get(_norm(ing))
        if e and (e["prohibited"] or e["limited"]):
            hits.append({"ingredient": ing, "std": e["std"], "prohibited": e["prohibited"], "limited": e["limited"]})
    return hits


def _compact(text: str) -> str:
    return re.sub(r"[\s.()\[\]·,_-]+", "", _norm(text))


def recalled(name: str, brand: str = "") -> List[Dict]:
    """식약처 회수·판매중지 목록에서 제품명이 겹치는 항목 (띄어쓰기·기호 무시, 4자 미만은 비교 안 함)."""
    n = _compact(name)
    if len(n) < 4:
        return []
    out = []
    for r in _RECALL:
        item = _compact(r.get("ITEM_NAME", ""))
        if len(item) >= 4 and (item in n or n in item):
            out.append(r)
            continue
        # 단어 단위: 사용자가 말한 단어(2자 이상, 3개 이상)가 모두 회수 제품명에 있으면 같은 제품으로 본다 ("04" 생략 등)
        words = [_compact(w) for w in re.split(r"[\s.()\[\]·,_-]+", _norm(name)) if len(_compact(w)) >= 2]
        if len(words) >= 3 and all(w in item for w in words):
            out.append(r)
    return out


def kr_reasons(hits: List[Dict], language: str = "ko", recall_hits: Optional[List[Dict]] = None) -> Dict[str, List[str]]:
    """{"block": [...], "info": [...]} — block 이 있으면 추천에서 뺀다."""
    country = COUNTRY_BY_LANG.get(language, "한국")
    watch = ["한국"] + ([country] if country != "한국" else [])
    block, info = [], []
    for h in hits:
        banned = [c for c in watch if c in h["prohibited"]]
        if banned:
            block.append(f"식약처 규제정보: {h['ingredient']}({h['std']})은(는) {', '.join(banned)}에서 사용 금지 성분")
    if recall_hits:
        block.append("식약처 회수·판매중지 목록에 같은 제품명이 있음")
    if not block:
        info.append(f"식약처 화장품 규제정보와 대조: {', '.join(watch)} 기준 금지 성분 없음")
        limited = [h for h in hits if any(c in h["limited"] for c in watch)]
        if limited:
            parts = [f"{h['ingredient']}({', '.join(c for c in watch if c in h['limited'])})" for h in limited]
            info.append(f"사용 한도가 정해진 성분 포함: {'; '.join(parts)} — 함량은 라벨 확인")
    return {"block": block, "info": info, "country": country}


def check(ingredients: List[str]) -> Optional[Dict]:
    """제품 전성분을 금지·제한·자외선 차단제 목록과 대조한다. 데이터가 없으면 None."""
    if not _LISTS:
        return None
    found = {"prohibited": [], "restricted": [], "sunscreen": []}
    for ing in ingredients or []:
        key = _norm(ing)
        for kind, table in _LISTS.items():
            hit = table.get(key)
            if hit:
                found[kind].append({"ingredient": ing, "listed_as": hit["inci"] or hit["name"],
                                    "cas": hit["cas"], "limit": hit["limit"]})
    return {**SOURCE, **found}


def reasons_ko(result: Dict) -> List[str]:
    """추천 이유에 붙일 짧은 한국어 문장 (사용자 언어로는 이후 번역 단계가 옮긴다)."""
    who = result["authority_ko"]
    if result["prohibited"]:
        names = ", ".join(h["ingredient"] for h in result["prohibited"])
        return [f"{who} 금지 성분 목록에 해당하는 성분이 있음({names})"]
    out = [f"{who} 금지 성분 목록과 대조해 해당 없음"]
    limited = result["restricted"] + result["sunscreen"]
    if limited:
        parts = [h["ingredient"] + (f" {re.split(r'[(（]', h['limit'])[0].strip()}" if h["limit"] else "") for h in limited]
        out.append(f"{who}가 사용 한도를 정한 성분 포함({', '.join(parts)}) — 함량은 라벨 확인")
    return out
