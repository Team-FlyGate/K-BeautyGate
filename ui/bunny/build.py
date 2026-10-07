"""토끼 채팅 화면을 파일 하나로 묶습니다.

art/*.webp 그림을 base64로 bunny.src.html에 넣어 public/bunny.html을 만듭니다.
외부 그림·글꼴·스크립트를 부르지 않으므로 어느 서버(로컬, Brev, Vercel)에서도 같은 화면이 나옵니다.

    python3 ui/bunny/build.py
"""
import base64
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
MARKER = "/*ART*/{}/*END*/"


def build() -> Path:
    source = (HERE / "bunny.src.html").read_text(encoding="utf-8")
    if MARKER not in source:
        raise SystemExit(f"bunny.src.html에 그림 자리표시 {MARKER} 가 없습니다.")
    art = {
        path.stem: "data:image/webp;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
        for path in sorted((HERE / "art").glob("*.webp"))
    }
    out = ROOT / "public" / "bunny.html"
    out.write_text(source.replace(MARKER, json.dumps(art, separators=(",", ":"))), encoding="utf-8")
    print(f"{out.relative_to(ROOT)} · 그림 {len(art)}개 · {out.stat().st_size / 1024:.0f} KB")
    return out


if __name__ == "__main__":
    build()
