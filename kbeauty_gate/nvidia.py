"""NVIDIA NIM 호출 (Nemotron 채팅, Nemotron 리랭커). 실패하면 None을 돌려주고 규칙 기반으로 계속 간다."""
import json
import urllib.error
import urllib.request
from typing import List, Optional

from .config import Settings


def _post(url: str, payload: dict, settings: Settings) -> Optional[dict]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.nvidia_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=settings.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"[nvidia] 호출 실패, 규칙 기반으로 계속합니다: {exc}")
        return None


def chat(settings: Settings, system: str, user: str, max_tokens: int = 1200) -> Optional[str]:
    if not settings.online:
        return None
    data = _post(settings.chat_url, {
        "model": settings.chat_model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }, settings)
    if not data:
        return None
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError):
        return None


def rerank(settings: Settings, query: str, passages: List[str]) -> Optional[List[float]]:
    """passages와 같은 순서의 관련도 점수(logit)를 돌려준다."""
    if not settings.online or not passages:
        return None
    data = _post(settings.rerank_url, {
        "model": settings.rerank_model,
        "query": {"text": query},
        "passages": [{"text": p} for p in passages],
        "truncate": "END",
    }, settings)
    if not data or "rankings" not in data:
        return None
    scores = [0.0] * len(passages)
    for r in data["rankings"]:
        scores[r["index"]] = float(r["logit"])
    return scores
