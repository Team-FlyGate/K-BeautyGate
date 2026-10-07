"""NVIDIA NIM 호출 (Nemotron 채팅, Nemotron 임베딩). 실패하면 None을 돌려주고 규칙 기반으로 계속 간다."""
import json
import math
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
        print(f"[nvidia] {payload.get('model')} 호출 실패: {exc}")
        return None


def chat(settings: Settings, system: str, user: str, max_tokens: int = 1200) -> Optional[str]:
    """설정한 모델부터 차례로 시도한다 (Ultra가 503이면 Super로)."""
    if not settings.online:
        return None
    for model in settings.chat_models:
        data = _post(settings.chat_url, {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
        }, settings)
        try:
            content = (data or {})["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError):
            content = ""
        if content.strip():
            settings.last_chat_model = model
            return content.strip()
    return None


def embed(settings: Settings, texts: List[str], input_type: str) -> Optional[List[List[float]]]:
    if not settings.online or not texts:
        return None
    data = _post(settings.embed_url, {
        "model": settings.embed_model,
        "input": texts,
        "input_type": input_type,
        "encoding_format": "float",
    }, settings)
    if not data or "data" not in data:
        return None
    return [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]


def relevance(settings: Settings, query: str, passages: List[str]) -> Optional[List[float]]:
    """다국어 질문과 한국어·영어 자료의 코사인 유사도. passages와 같은 순서로 돌려준다."""
    q = embed(settings, [query], "query")
    p = embed(settings, passages, "passage")
    if not q or not p:
        return None

    def cos(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) + 1e-9)

    return [cos(q[0], v) for v in p]
