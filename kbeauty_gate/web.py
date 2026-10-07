"""라이브 데모용 대화형 웹앱. 외부 패키지 없이 표준 라이브러리 http.server만 쓴다.

    python3 -m kbeauty_gate.web --input hackathon/input --output hackathon/output --port 8080
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .agent import run
from .config import get_settings
from .conversation import build_turn

STATIC = Path(__file__).resolve().parent / "static"
ROOT = Path(__file__).resolve().parent.parent


class Handler(BaseHTTPRequestHandler):
    input_dir: Path
    output_dir: Path

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, data: dict) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/status":
            s = get_settings()
            self._json(200, {"online": s.online, "chat_models": s.chat_models, "embed_model": s.embed_model})
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        if self.path != "/api/chat":
            self._send(404, b"not found", "text/plain")
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        message = (body.get("message") or "").strip()
        if not message:
            self._json(400, {"error": "메시지가 비어 있어요."})
            return
        try:
            settings = get_settings()
            defaults = json.loads((ROOT / "profiles" / "visitor_jp.json").read_text(encoding="utf-8"))
            for k in ("request", "check_items", "name"):
                defaults.pop(k, None)
            turn = build_turn(settings, message, body.get("state"), defaults)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            profile = turn["profile"] if turn["mode"] == "beauty" else None
            result = run(self.input_dir, self.output_dir, profile, turn["request"], turn["mode"])
            self._json(200, {"turn": turn, "result": result})
        except Exception as exc:  # 데모 화면에 오류를 그대로 보여 준다
            self._json(500, {"error": str(exc)})

    def log_message(self, fmt: str, *args) -> None:
        print("[web]", fmt % args)


def main() -> None:
    parser = argparse.ArgumentParser(prog="kbeauty_gate.web")
    parser.add_argument("--input", default="/hackathon/input")
    parser.add_argument("--output", default="/hackathon/output")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    Handler.input_dir = Path(args.input).resolve()
    Handler.output_dir = Path(args.output).resolve()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"K-BeautyGate demo → http://localhost:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
