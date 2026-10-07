"""성분 이름과 다른 이름(이명) 확장.

식약처 화장품 원료성분정보 API(공공데이터포털)를 쓸 수 있으면 이명을 더하고, 키가 없거나 호출이 실패하면
대한화장품협회 표준 성분명으로 대조한 로컬 대응표만 쓴다. "향료를 빼 주세요"가 Fragrance 뿐 아니라
Parfum, Perfume 까지 걸러지게 하려는 것이다.

설정(환경 변수):
  MFDS_API_KEY         공공데이터포털 일반 인증키(Encoding 값 그대로). 없으면 네트워크를 쓰지 않는다
  MFDS_INGREDIENT_URL  오퍼레이션 전체 주소. 공공데이터포털 명세 화면의 요청주소를 그대로 넣는다
  MFDS_QUERY_PARAM     성분명 검색 변수 이름 (명세 화면에서 확인, 기본값은 추정)
"""
import csv
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

GLOSSARY = Path(__file__).resolve().parent.parent / "hackathon" / "input" / "beauty" / "ingredients" / "ingredient_glossary.csv"
# 식약처 기관 경로 둘(1471000, 1471057). OpenShell 정책도 이 경로의 GET 만 허용한다
OFFICIAL_PREFIXES = ("https://apis.data.go.kr/1471000/", "https://apis.data.go.kr/1471057/")
TIMEOUT = 4

_glossary: Optional[List[Dict]] = None
_api_cache: Dict[str, Set[str]] = {}
_last_source = "local"


def reset_cache() -> None:
    global _glossary, _last_source
    _glossary, _last_source = None, "local"
    _api_cache.clear()


def last_source() -> str:
    """Where the most recent expansion got its aliases: 'mfds' or 'local'."""
    return _last_source


def _rows() -> List[Dict]:
    global _glossary
    if _glossary is None:
        try:
            with GLOSSARY.open(encoding="utf-8") as f:
                _glossary = list(csv.DictReader(f))
        except OSError:
            _glossary = []
    return _glossary


def _names(row: Dict) -> Set[str]:
    names = {row.get("inci", ""), row.get("name_ko", "")}
    names.update(re.split(r"\s*\|\s*", row.get("kcia_en", "") or ""))
    return {n.strip().lower() for n in names if n and n.strip()}


def _local(word: str) -> Set[str]:
    word = word.strip().lower()
    out = {word}
    for row in _rows():
        names = _names(row)
        if word in names or (row.get("avoid_group") or "").lower() == word:
            out |= names
    return out


def _strings(node) -> Iterable[str]:
    if isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)
    elif isinstance(node, str):
        yield node


def _items(payload) -> List[Dict]:
    """data.go.kr wraps rows as body.items, body.items.item, or a bare list; accept all of them."""
    body = payload.get("body", payload) if isinstance(payload, dict) else payload
    items = body.get("items", body) if isinstance(body, dict) else body
    if isinstance(items, dict):
        items = items.get("item", [items])
    if isinstance(items, dict):
        items = [items]
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def _mfds(word: str) -> Optional[Set[str]]:
    key = os.environ.get("MFDS_API_KEY") or os.environ.get("MFDS_SERVICE_KEY")
    url = os.environ.get("MFDS_INGREDIENT_URL", "")
    if not key or not url.startswith(OFFICIAL_PREFIXES):
        return None
    if word in _api_cache:
        return _api_cache[word]
    params = {"type": "json", "pageNo": 1, "numOfRows": 5, os.environ.get("MFDS_QUERY_PARAM", "INGR_ENG_NAME"): word}
    # The portal's key is already URL-encoded; passing it through urlencode again turns % into %25 and auth fails
    req = urllib.request.Request(f"{url}?serviceKey={key}&{urllib.parse.urlencode(params)}",
                                 headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError) as exc:  # key not yet registered, timeout, OpenShell denial, non-JSON error page
        print(f"[mfds] 성분 조회 실패, 로컬 대응표 사용: {exc}")
        return None
    found: Set[str] = set()
    for item in _items(payload):
        values = list(_strings(item))
        if any(word in v.lower() for v in values):
            for value in values:
                found.update(p.strip().lower() for p in re.split(r"[,;|/]", value) if 1 < len(p.strip()) < 60)
    _api_cache[word] = found
    return found


def expand_avoid(words: Iterable[str]) -> Set[str]:
    """Return every name that should count as the avoided ingredient, in lower case."""
    global _last_source
    terms: Set[str] = set()
    used_api = False
    for word in words or []:
        if not word or not word.strip():
            continue
        local = _local(word)
        api = _mfds(word.strip().lower())
        if api:
            used_api = True
            local |= api
        terms |= local
    _last_source = "mfds" if used_api else "local"
    return terms
