"""Vercel 서버리스 함수: POST /api/chat"""
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kbeauty_gate.web import chat_response, read_json, send_json  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        code, data = chat_response(read_json(self))
        send_json(self, code, data)
