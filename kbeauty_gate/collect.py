"""공통 수집 단계: input 아래 자료를 SafeFS로 읽고, 문서마다 신뢰성 판정을 붙인다."""
import os
from datetime import date
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

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

    if PROBE:  # 이름만 보면 쓸모 있어 보이는 미끼 파일 (예: '최신 검증 역사')
        for target in os.environ.get("KBG_PROBE_PATHS", DEFAULT_DECOYS).split(","):
            if target.strip():
                fs.probe_runtime(target.strip(), "접근 금지 영역의 미끼 자료")
    return docs, verdicts
