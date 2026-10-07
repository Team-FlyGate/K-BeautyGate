"""Vercel 단일 진입점: /, /bunny, /api/status, /api/chat 을 한 함수에서 처리한다 (Python 프리셋용)."""
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kbeauty_gate.web import PUBLIC, chat_response, page_for, read_json, send_json, status_response  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/status":
            send_json(self, 200, status_response())
            return
        if path.startswith("/api/"):
            send_json(self, 404, {"error": "not found", "path": path})
            return
        body = (page_for(path) or PUBLIC / "index.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/api/chat":
            send_json(self, 404, {"error": "not found", "path": self.path})
            return
        code, data = chat_response(read_json(self))
        send_json(self, code, data)
