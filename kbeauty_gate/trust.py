"""신뢰성 판단 하네스: 자료와 제품을 쓰기 전에 출처·유효기간·광고성·숨은 지시·원산지를 검사한다."""
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List

from . import regulatory
from .guard import find_injections

AD_PATTERNS = [
    r"완벽\s*(해결|대응)", r"100\s*%\s*정품", r"부작용\s*0", r"원고료", r"협찬", r"제공받아",
    r"sponsored", r"guaranteed", r"miracle", r"기적", r"완벽하게\s*보존", r"홍보\s*문안",
    r"인증\s*자료는\s*첨부되지\s*않",
]
STALE_MARKERS = [r"캐시", r"cache", r"확인\s*안\s*됨", r"저장본", r"미확인", r"이전\s*카드", r"(^|[_\W])old([_\W]|$)"]
IRRELEVANT_MARKERS = [r"무관", r"unrelated"]
UNCERTAIN_MARKERS = [r"OCR", r"훼손", r"추정", r"진행\s*중", r"가능성"]
DATE_RE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")


@dataclass
class Verdict:
    target: str
    trusted: bool
    score: float
    flags: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"target": self.target, "trusted": self.trusted, "score": round(self.score, 2),
                "flags": self.flags, "reasons": self.reasons}


def _dates(text: str) -> List[date]:
    out = []
    for y, m, d in DATE_RE.findall(text):
        try:
            out.append(date(int(y), int(m), int(d)))
        except ValueError:
            pass
    return out


def assess_document(name: str, text: str, visit: date) -> Verdict:
    v = Verdict(target=name, trusted=True, score=1.0)

    injections = find_injections(text)
    if injections:
        v.flags.append("prompt_injection")
        v.reasons.append(f"자료 안에 에이전트를 향한 지시가 있음: {injections[0]!r}")
        v.score -= 1.0

    ads = [p for p in AD_PATTERNS if re.search(p, text, flags=re.IGNORECASE)]
    if ads:
        v.flags.append("advertising")
        v.reasons.append("인증 근거 없는 보장 문구 또는 협찬 표기")
        v.score -= 0.6

    if any(re.search(p, text + name, flags=re.IGNORECASE) for p in STALE_MARKERS):
        years = [int(y) for y in re.findall(r"20\d{2}", name + text)]
        if years and max(years) < visit.year:
            v.flags.append("stale")
            v.reasons.append(f"{max(years)}년 캐시 자료로 현재 운영 정보와 다를 수 있음")
            v.score -= 0.6

    if any(re.search(p, text) for p in IRRELEVANT_MARKERS):
        v.flags.append("irrelevant")
        v.reasons.append("자료 스스로 현재 요청·방문단과 무관하다고 밝힘")
        v.score -= 1.0

    if any(re.search(p, text) for p in UNCERTAIN_MARKERS):
        v.flags.append("uncertain")
        v.reasons.append("판독·연대가 확정되지 않아 단정 표현 금지, '확인 필요'로 표시")
        v.score -= 0.2

    dates = _dates(text)
    if "~" in text and dates and max(dates) < visit:
        v.flags.append("expired")
        v.reasons.append(f"운영 기간이 {max(dates).isoformat()}에 끝나 방문일({visit.isoformat()})과 맞지 않음")
        v.score -= 0.8

    v.score = max(v.score, 0.0)
    v.trusted = v.score >= 0.5 and "prompt_injection" not in v.flags
    if v.trusted and not v.reasons:
        v.reasons.append("기간·출처 문제 없음")
    return v


def assess_product(product: Dict, registry: Dict[str, Dict]) -> Verdict:
    """정품 판단은 '공식 유통 확인' 기준이다. 해외 제조라는 사실만으로 가품 처리하지 않는다."""
    v = Verdict(target=product["name"], trusted=True, score=1.0)
    brand = registry.get(product.get("brand", ""))
    made_in = product.get("made_in", "unknown")

    if brand is None:
        v.flags.append("unregistered_brand")
        v.reasons.append("국내 브랜드 등록부에 없어 공식 유통을 확인할 수 없음")
        v.score -= 0.5
        if made_in != "KR":
            v.flags.append("korean_label_foreign_origin" if made_in != "unknown" else "origin_unknown")
            v.reasons.append(f"한국 브랜드처럼 보이지만 제조국 {made_in}")
            v.score -= 0.3
    elif made_in != "KR":
        v.flags.append("overseas_manufacturing")
        v.reasons.append(f"등록 브랜드의 해외 제조({made_in}): 공식 유통이면 정품")
    if product.get("source") == "open_market_listing":
        v.flags.append("open_market")
        v.reasons.append("오픈마켓 등록 정보로 공식 판매처 아님")
        v.score -= 0.2
    if product.get("label_note"):
        v.reasons.append(f"라벨 메모: {product['label_note']}")
    kr_hits = regulatory.check_kr(product.get("ingredients") or []) or []
    kr_banned = [h for h in kr_hits if "한국" in h["prohibited"]]
    if kr_banned:
        h = kr_banned[0]
        v.flags.append("kr_prohibited_ingredient")
        v.reasons.append(f"식약처 규제정보: {h['ingredient']}({h['std']})은(는) 한국 등 {len(h['prohibited'])}개 국가·지역에서 "
                         "사용 금지 성분 — 공식 규제 데이터 기준 안전 경고")
        v.score -= 0.5
    reg = regulatory.check(product.get("ingredients") or [])
    if reg and reg["prohibited"] and not kr_banned:
        v.flags.append("tw_prohibited_ingredient")
        v.reasons.append(regulatory.reasons_ko(reg)[0] + " — 공식 규제 데이터 기준 안전 경고")
        v.score -= 0.5

    v.score = max(v.score, 0.0)
    v.trusted = v.score >= 0.7
    if v.trusted:
        v.reasons.insert(0, f"국내 등록 브랜드({brand['manufacturer']}), 공식 유통 확인")
    else:
        v.flags.insert(0, "disguised_k_beauty")
    return v


def assess_unlisted(name: str) -> Dict:
    """우리 자료에 없는 제품: 식약처 회수·판매중지 목록과 대조하고, 없으면 판단을 보류한다."""
    hits = regulatory.recalled(name)
    if hits:
        r = hits[0]
        d = str(r.get("RECALL_COMMAND_DATE") or "")
        when = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d
        return {"target": name, "trusted": False, "score": 0.0,
                "flags": ["mfds_recalled", "do_not_buy"],
                "reasons": [f"식약처 회수·판매중지 대상: {r.get('ITEM_NAME')} ({r.get('ENTP_NAME')})",
                            f"사유: {r.get('DISPS_CONT')} · 회수 명령일 {when}",
                            "구매하지 마세요 — 공식 회수 정보 기준"]}
    reasons = ["자료에 없는 제품이라 판단 보류"]
    if regulatory.available():
        reasons.append("식약처 회수·판매중지 목록에는 없음 (정품 여부는 매장에서 라벨·제조사 확인)")
    return {"target": name, "trusted": False, "score": 0.0, "flags": ["unverified"], "reasons": reasons}
