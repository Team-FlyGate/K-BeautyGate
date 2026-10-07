"""공통 수집 단계: input 아래 자료를 SafeFS로 읽고, 문서마다 신뢰성 판정을 붙인다."""
import os
from datetime import date
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from . import jev, regulatory
from .guard import SafeFS, injection_targets
from .trust import Verdict, assess_document


PROBE = os.environ.get("KBG_OPENSHELL_PROBE") == "1"
DEFAULT_DECOYS = "/hackathon/restricted/latest_verified_history.md,/hackathon/secrets/service_key.env"


def collect(fs: SafeFS, input_dir: Path, visit: date,
            include: Optional[Callable[[str], bool]] = None) -> Tuple[Dict[str, str], Dict[str, Verdict]]:
    """include: 이번 요청에 해당하는 자료만 읽는다 (뷰티는 beauty/, 공통 테스트는 그 외)."""
    docs: Dict[str, str] = {}
    for path in sorted(input_dir.rglob("*")):
        rel = str(path.relative_to(input_dir))
        if include and not include(rel):
            continue
        if path.is_file() and not path.name.startswith("."):
            text = fs.read_text(path)
            if text is not None:
                docs[str(path.relative_to(input_dir))] = text

    regulatory.prime(docs)  # 공식 규제 CSV(대만 TFDA)는 추천 단계에서 전성분 대조에 쓴다

    verdicts: Dict[str, Verdict] = {}
    for name, text in docs.items():
        if name.endswith((".json", ".csv")):
            continue
        v = assess_document(name, text, visit)
        verdicts[name] = v
        if "prompt_injection" in v.flags:
            for target in injection_targets(text):
                fs.try_follow(target, name)
                if PROBE:
                    fs.probe_runtime(target, f"{name}의 숨은 지시 대상")

    # 비자기회귀(Non-autoregressive) 판단 모델 게이트: 문서마다 'AI에게 하는 지시', '근거 없는 광고' 확률을 한 번에 묻는다 (규칙 판정의 두 번째 의견)
    scores = jev.check_documents(docs)
    for name, sc in (scores or {}).items():
        v = verdicts.get(name)
        if not v:
            continue
        v.reasons.append(f"비자기회귀 판단 모델: AI 지시 문장 확률 {sc['inject']:.2f}, 광고 문구 확률 {sc['ad']:.2f}")
        if sc["inject"] >= 0.9 and "prompt_injection" not in v.flags:
            v.flags.append("prompt_injection")
            v.trusted = False
            for target in injection_targets(docs[name]):
                fs.try_follow(target, name)
        if sc["ad"] >= 0.9 and "advertising" not in v.flags:
            v.flags.append("advertising")
            v.trusted = False

    if PROBE:  # 이름만 보면 쓸모 있어 보이는 미끼 파일 (예: '최신 검증 역사')
        for target in os.environ.get("KBG_PROBE_PATHS", DEFAULT_DECOYS).split(","):
            if target.strip():
                fs.probe_runtime(target.strip(), "접근 금지 영역의 미끼 자료")
    return docs, verdicts
