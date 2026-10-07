"""데모 웹앱. 외부 패키지 없이 표준 라이브러리 http.server만 쓴다.

로컬·Brev:  python3 -m kbeauty_gate.web --input hackathon/input --output hackathon/output --port 8080
Vercel:     public/index.html + api/chat.py, api/status.py 가 아래 chat_response()/status_response()를 쓴다.
토끼 화면:  /bunny 에서 public/bunny.html (ui/bunny/build.py로 만든 단일 파일)을 연다.
"""
import argparse
import json
import os
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Optional, Tuple

from .agent import run
from .config import get_settings
from .conversation import build_turn

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"


def default_dirs() -> Tuple[Path, Path]:
    """Vercel은 /tmp만 쓸 수 있으므로 결과물은 그쪽에 둔다."""
    input_dir = Path(os.environ.get("KBG_INPUT", ROOT / "hackathon" / "input"))
    if os.environ.get("VERCEL"):
        output_dir = Path(tempfile.gettempdir()) / "kbeauty-output"
    else:
        output_dir = Path(os.environ.get("KBG_OUTPUT", ROOT / "hackathon" / "output"))
    return input_dir.resolve(), output_dir.resolve()


def page_for(path: str) -> Optional[Path]:
    """화면 경로: / 는 기존 화면, /bunny 는 토끼 캐릭터 채팅 화면 (public/bunny.html)."""
    path = path.split("?", 1)[0].rstrip("/") or "/"
    if path == "/" and os.environ.get("KBG_HOME") == "bunny":
        return PUBLIC / "bunny.html"  # 토끼 화면을 첫 화면으로 쓰는 배포 (환경변수 KBG_HOME=bunny)
    if path in ("/", "/index.html"):
        return PUBLIC / "index.html"
    if path in ("/bunny", "/bunny.html"):
        return PUBLIC / "bunny.html"
    return None


def status_response() -> Dict:
    s = get_settings()
    return {"online": s.online, "chat_models": s.chat_models, "embed_model": s.embed_model,
            "openshell": not bool(os.environ.get("VERCEL"))}


def chat_response(body: Dict, input_dir: Optional[Path] = None, output_dir: Optional[Path] = None) -> Tuple[int, Dict]:
    if input_dir is None or output_dir is None:
        input_dir, output_dir = default_dirs()
    message = (body.get("message") or "").strip()
    if not message:
        return 400, {"error": "메시지가 비어 있어요."}
    try:
        settings = get_settings()
        sample = json.loads((ROOT / "profiles" / "visitor_jp.json").read_text(encoding="utf-8"))
        # 샘플 프로필에서는 일정 틀(날짜·시간·지역·예산)만 기본값으로 쓴다.
        # 피부 타입·고민·피할 성분은 사용자가 말한 것만 쓴다 (말하지 않은 '향료 제외'가 끼어들지 않게).
        defaults = {k: sample[k] for k in ("visit_date", "time_window", "areas", "budget_krw") if k in sample}
        turn = build_turn(settings, message, body.get("state"), defaults)
        output_dir.mkdir(parents=True, exist_ok=True)
        profile = turn["profile"]
        result = run(input_dir, output_dir, profile, turn["request"], turn["mode"])
        return 200, {"turn": turn, "result": result}
    except Exception as exc:  # 데모 화면에 오류를 그대로 보여 준다
        return 500, {"error": str(exc)}


def send_json(handler: BaseHTTPRequestHandler, code: int, data: Dict) -> None:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json(handler: BaseHTTPRequestHandler) -> Dict:
    length = int(handler.headers.get("Content-Length", 0))
    return json.loads(handler.rfile.read(length) or b"{}")


class Handler(BaseHTTPRequestHandler):
    input_dir: Path
    output_dir: Path

    def do_GET(self) -> None:
        page = page_for(self.path)
        if page:
            body = page.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/status":
            send_json(self, 200, status_response())
        else:
            send_json(self, 404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/api/chat":
            send_json(self, 404, {"error": "not found"})
            return
        code, data = chat_response(read_json(self), self.input_dir, self.output_dir)
        send_json(self, code, data)

    def log_message(self, fmt: str, *args) -> None:
        print("[web]", fmt % args)


def main() -> None:
    parser = argparse.ArgumentParser(prog="kbeauty_gate.web")
    parser.add_argument("--input", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    in_dir, out_dir = default_dirs()
    Handler.input_dir = Path(args.input).resolve() if args.input else in_dir
    Handler.output_dir = Path(args.output).resolve() if args.output else out_dir
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"K-BeautyGate demo → http://localhost:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
