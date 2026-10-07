"""애플리케이션 계층 가드.

실제 차단은 OpenShell 정책(policy/openshell-policy.yaml)이 커널·프록시 수준에서 한다.
이 모듈은 같은 경계를 앱 안에서도 한 번 더 지키고, 무엇을 왜 막았는지 감사 로그로 남긴다.
"""
import json
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import List, Optional

FORBIDDEN_DIRS = ("restricted", "secrets")

INJECTION_PATTERNS = [
    r"이전\s*지시.{0,10}무시",
    r"ignore\s+(all\s+)?(previous|prior)\s+instructions",
    r"(업로드|전송|보내)\s*(하세요|해\s*주세요|하라)",
    r"업로드한\s*뒤",
    r"\bupload\b.{0,40}(key|secret|file|customer)",
    r"/hackathon/(secrets|restricted)",
    r"https?://\S+/(api|upload)\S*",
    r"아무\s*말도\s*하지\s*마",
    r"AI\s*어시스턴트에게",
]


class AuditLog:
    def __init__(self) -> None:
        self.events: List[dict] = []

    def record(self, action: str, target: str, decision: str, reason: str) -> None:
        self.events.append({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "action": action,
            "target": target,
            "decision": decision,
            "reason": reason,
        })

    def write(self, path: Path) -> None:
        path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in self.events) + "\n", encoding="utf-8")


class SafeFS:
    """input은 읽기만, output은 쓰기만 허용한다. restricted·secrets는 경로에 닿기 전에 거부한다."""

    def __init__(self, input_dir: Path, output_dir: Path, audit: AuditLog) -> None:
        self.input_dir = input_dir.resolve()
        self.output_dir = output_dir.resolve()
        self.audit = audit
        self.saved: List[str] = []

    def _forbidden(self, path: Path) -> Optional[str]:
        parts = set(path.resolve().parts)
        for name in FORBIDDEN_DIRS:
            if name in parts:
                return f"'{name}' 영역은 접근 금지"
        return None

    def read_text(self, path: Path) -> Optional[str]:
        reason = self._forbidden(path)
        if reason is None and self.input_dir not in path.resolve().parents:
            reason = "input 밖의 경로"
        if reason:
            self.audit.record("read", str(path), "DENIED", reason)
            return None
        self.audit.record("read", str(path.resolve().relative_to(self.input_dir)), "ALLOWED", "input 자료")
        return path.read_text(encoding="utf-8")

    def write_text(self, name: str, content: str) -> Path:
        target = (self.output_dir / name).resolve()
        if self.output_dir not in target.parents:
            self.audit.record("write", name, "DENIED", "output 밖의 경로")
            raise PermissionError(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.audit.record("write", name, "ALLOWED", "결과물 저장")
        self.saved.append(str(target))
        return target

    def probe_runtime(self, target: str, why: str) -> None:
        """발표용(KBG_OPENSHELL_PROBE=1): 앱 가드를 건너뛰고 실제로 열어/보내 본다.

        OpenShell 샌드박스 안이라면 런타임이 막고, 그 거부가 여기와 `openshell logs`에 함께 남는다.
        파일은 열기만 하고 내용은 읽지 않으며, URL에는 본문 없이 HEAD 요청만 보낸다.
        """
        try:
            if target.startswith("http") or ("." in target and not target.startswith("/")):
                url = target if target.startswith("http") else f"https://{target}/"
                urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=5).close()
            else:
                os.close(os.open(target, os.O_RDONLY))
            self.audit.record("runtime-probe", target, "NOT_BLOCKED",
                              f"{why} — 런타임 차단 없음(OpenShell 밖에서 실행 중). 내용은 읽지 않음")
        except OSError as exc:
            # Errno 13(권한 거부)만 런타임 정책 차단으로 기록한다. 파일 없음(Errno 2)·DNS 실패 등은 그대로 구분한다.
            errno = getattr(exc, "errno", None) or getattr(getattr(exc, "reason", None), "errno", None)
            if errno == 13:
                note = "런타임 정책이 거부(Errno 13, OpenShell 샌드박스)"
            elif errno == 2:
                note = "대상 파일 없음(Errno 2) — 정책 차단 여부와 무관"
            else:
                note = "열기·전송 실패(정책 차단이 아닐 수 있음)"
            self.audit.record("runtime-probe", target, "DENIED", f"{why} — {note}: {exc}")

    def try_follow(self, instruction_target: str, source: str) -> None:
        """자료 속 지시가 가리키는 경로·URL은 열지 않고, 거부 기록만 남긴다."""
        self.audit.record("follow-instruction", instruction_target, "DENIED",
                          f"자료({source}) 안의 지시는 사용자 요청이 아님")


def find_injections(text: str) -> List[str]:
    hits = []
    for pattern in INJECTION_PATTERNS:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            hits.append(m.group(0))
    return hits


def injection_targets(text: str) -> List[str]:
    targets = re.findall(r"/hackathon/[\w./-]+", text)
    targets += re.findall(r"https?://[^\s)]+", text)
    targets += [d for d in re.findall(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.example(?![A-Za-z0-9-])", text)
                if not any(d in t for t in targets)]
    return sorted(set(targets))
