"""Vercel 서버리스 함수: GET /api/status"""
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kbeauty_gate.web import send_json, status_response  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        send_json(self, 200, status_response())
