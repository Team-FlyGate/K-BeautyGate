"""라이브 데모용 웹앱. 외부 패키지 없이 표준 라이브러리 http.server만 쓴다.

    python3 -m kbeauty_gate.web --input hackathon/input --output hackathon/output --port 8080
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .agent import run

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

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/sample":
            sample = (ROOT / "profiles" / "visitor_jp.json").read_bytes()
            self._send(200, sample, "application/json; charset=utf-8")
        elif self.path == "/api/task":
            task = ROOT / "TASK.md"
            text = task.read_text(encoding="utf-8") if task.is_file() else ""
            self._send(200, json.dumps({"request": text}, ensure_ascii=False).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        if self.path != "/api/run":
            self._send(404, b"not found", "text/plain")
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        mode = body.get("mode", "beauty")
        profile = body.get("profile") if mode == "beauty" else None
        request = body.get("request") or (profile or {}).get("request", "")
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            result = run(self.input_dir, self.output_dir, profile, request, mode)
            self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"), "application/json")
        except Exception as exc:  # 데모 화면에 오류를 그대로 보여 준다
            self._send(500, json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8"), "application/json")

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
