"""공통 수집 단계: input 아래 자료를 SafeFS로 읽고, 문서마다 신뢰성 판정을 붙인다."""
from datetime import date
from pathlib import Path
from typing import Dict, Tuple

from .guard import SafeFS, injection_targets
from .trust import Verdict, assess_document


def collect(fs: SafeFS, input_dir: Path, visit: date) -> Tuple[Dict[str, str], Dict[str, Verdict]]:
    docs: Dict[str, str] = {}
    for path in sorted(input_dir.rglob("*")):
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
    return docs, verdicts
