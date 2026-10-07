import argparse
import json
from pathlib import Path

from .agent import run

DEFAULT_REQUEST = Path(__file__).resolve().parent.parent / "TASK.md"


def main() -> None:
    parser = argparse.ArgumentParser(prog="kbeauty_gate", description="K-BeautyGate 에이전트 실행")
    parser.add_argument("--input", default="/hackathon/input", help="읽기 전용 자료 폴더")
    parser.add_argument("--output", default="/hackathon/output", help="결과물 폴더")
    parser.add_argument("--profile", help="뷰티 방문객 프로필 JSON (없으면 공통 테스트 요청으로 처리)")
    parser.add_argument("--request", help="사용자 요청 문장 (없으면 프로필의 request 또는 TASK.md)")
    parser.add_argument("--mode", choices=["auto", "beauty", "culture"], default="auto")
    args = parser.parse_args()

    profile = json.loads(Path(args.profile).read_text(encoding="utf-8")) if args.profile else None
    request = args.request or (profile or {}).get("request") or (
        DEFAULT_REQUEST.read_text(encoding="utf-8") if DEFAULT_REQUEST.is_file() else "")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    result = run(Path(args.input), output, profile, request, args.mode)

    if result["mode"] == "beauty":
        print(f"[beauty] 추천 {len(result['recommendations'])}개, 동선 {len(result['route'])}곳 → {output}")
        for c in result["authenticity_checks"]:
            print(f"정품 확인: {c['target']} → {'정품' if c['trusted'] else '위장 K-뷰티 의심'}")
    else:
        print(f"[culture] 방문일 {result['visit_date']}, 인원 {len(result['people'])}명, 적용 공지 {len(result['notices'])}건 → {output}")


if __name__ == "__main__":
    main()
