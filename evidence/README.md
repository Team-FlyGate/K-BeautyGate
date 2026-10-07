# OpenShell 실행 기록

Brev 인스턴스(OpenShell 0.1.2)에서 실제로 돌린 출력이다. **파일 이름의 시각은 UTC**(한국 시각 = +9시간).
과정 전체는 `docs/openshell-setup-log.md`. API 키는 어디에도 없고, 에이전트가 본 값은 자리표시자뿐이다.

| 파일 | 내용 |
|---|---|
| `smoke_0304.txt` | 첫 정책으로 허용(input 읽기, output 쓰기)과 차단(restricted, secrets, 숨은 지시 업로드) 시험, 게이트웨이 DENIED 로그 |
| `provider_0326.txt` | 에이전트가 보는 `NVIDIA_API_KEY` 가 `openshell:resolve:env:...` 자리표시자인데 호출은 되는 것, 허용과 차단 로그 |
| `run_0347/` | 에이전트(`python3 -m kbeauty_gate`)를 샌드박스 안에서 실행한 결과물 6개 |
| `run_0347/audit.jsonl` | **판단 우회 시험**(`KBG_OPENSHELL_PROBE=1`). 앱 가드가 거부한 기록과, 가드를 건너뛰고 열어 봤을 때 OpenShell 이 막은 기록이 함께 있다 |
| `run_0347/openshell_log.txt` | 같은 시각 게이트웨이의 ALLOWED, DENIED 로그(OCSF 형식) |

결과물 속 인물, 지명, 연락처는 주최 측 공통 테스트의 가상 데이터다.
