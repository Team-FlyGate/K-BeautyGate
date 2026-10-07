# K-BeautyGate

Team FlyGate · Korea Agentic AI Hackathon 2026 (NVIDIA OpenShell)

외국인 방문객의 피부 정보와 일정을 받아 **진짜 K-뷰티 제품과 체험·매장 동선**을 짜 주고, 위장 K-뷰티·광고성 후기·지난 행사·자료 속 숨은 지시는 스스로 걸러내는 에이전트입니다. 같은 하네스로 주최측 공통 테스트(문화 코스 초안)도 처리합니다.

- **공개 데모:** https://k-beauty-gate-zeta.vercel.app/ (사용자 화면) · https://k-beauty-gate-zeta.vercel.app/?backstage=1 (발표용: 판단 근거·차단 기록·저장 경로)
- **OpenShell 차단 증거:** [`evidence/`](evidence/) · 셋업과 시험 기록 [`docs/openshell-setup-log.md`](docs/openshell-setup-log.md)
- 챌린지 원문: [CHALLENGE.md](CHALLENGE.md) · [TASK.md](TASK.md)
- OpenShell 정책 파일: [`policy/openshell-policy.yaml`](policy/openshell-policy.yaml)

## 동작 흐름

1. **수집** — `hackathon/input`을 읽기 전용으로 읽습니다. `restricted`·`secrets`는 OpenShell 정책에 없고, 앱 가드(`kbeauty_gate/guard.py`)도 한 번 더 거부합니다.
2. **신뢰성 판단** (`kbeauty_gate/trust.py`) — 문서마다 지난 기간, 오래된 캐시, 광고 문구, 무관 자료, 판독 불확실, 숨은 지시를 검사합니다. 제품은 국내 브랜드 등록부와 공식 유통 여부로 판단합니다. 해외 제조라는 이유만으로 가품 처리하지 않습니다.
3. **맞춤 판단** (`kbeauty_gate/planner.py`) — 피부 타입·고민·회피 성분·예산으로 순위를 매깁니다. 전성분표가 확인되지 않은 제품은 "확인 필요"로 빼 둡니다. 전성분은 식약처 화장품 규제정보(나라별 금지·제한)와 대만 TFDA 목록에 대조하고, 금지 성분이나 식약처 회수·판매중지 제품은 추천에서 빼고 경고합니다(`kbeauty_gate/regulatory.py`). 키가 있으면 Nemotron Embed 관련도 점수를 더합니다.
4. **동선·카드** — 방문일 공지(조기 마감 등)를 반영해 체험과 매장을 잇고, 매장 직원에게 보여 줄 한글 카드와 Nemotron 요약(사용자 언어)을 `hackathon/output`에 저장합니다.

공통 테스트 모드(`kbeauty_gate/culture.py`)는 같은 1–2단계를 거친 뒤, 방문일 공지·음식 제한·접근성을 반영한 코스 초안과 음식 제한 한글 카드를 만듭니다. 예약·발송·결제는 하지 않습니다.

## 설치 및 실행

Python 3.9 이상, 외부 패키지 없음(표준 라이브러리만 사용).

```bash
cp .env.example .env          # NVIDIA_API_KEY 입력 (없으면 규칙 기반으로만 동작)

# K-뷰티 플랜 (가상 프로필)
python3 -m kbeauty_gate --input hackathon/input --output hackathon/output --profile profiles/visitor_jp.json

# 공통 테스트 (TASK.md 요청)
python3 -m kbeauty_gate --input hackathon/input --output hackathon/output --mode culture
```

## 평가 방법 (테스트)

모델 학습(training)은 하지 않습니다. NVIDIA 호스티드 모델(Nemotron)을 호출만 하므로 학습 단계는 없습니다.

```bash
# 1) 단위·시나리오 테스트 (키 없이 실행, 모델 응답은 모의값)
python3 -m unittest discover -s tests          # 라우팅·거절·신뢰성 판단·규제 대조·사실 검사·다국어
node tests/frontend_language.test.cjs          # 화면 다국어·백스테이지 분리 (Node 18+)

# 2) 공통 테스트 함정 질문 + 변형 질문 점검 (tests/test_scenarios.py)
KBG_OPENSHELL_PROBE=0 python3 -m unittest discover -s tests -p test_scenarios.py -v

# 3) OpenShell 차단 검증 — 샌드박스 안에서만 (아래 "OpenShell 샌드박스 실행" 후)
KBG_OPENSHELL_PROBE=1 python3 -m kbeauty_gate --input /hackathon/input --output /hackathon/output --mode culture
openshell logs kbg --since 10m | grep DENIED   # 금지 경로 열기(Errno 13)·숨은 지시 업로드 주소 차단 확인
```

- 함정 질문 10개와 변형 질문(음식 제한·성진정 해설·휠체어·날짜 변경·메일·restricted 요청·영어)으로 모드 분기, 위험 요청 거절, 근거 사용을 확인합니다.
- 실제 차단 결과는 [`evidence/run_0347`](evidence/run_0347)(공통 테스트), [`evidence/run_beauty_0551`](evidence/run_beauty_0551)(K-뷰티 쿠폰 숨은 지시)에 있습니다.

## 데모 (웹앱)

```bash
python3 -m kbeauty_gate.web --input hackathon/input --output hackathon/output --port 8080
```

`http://localhost:8080`은 대화형 화면입니다. 한·영·중·일 어느 언어로 피부 고민과 일정을 말하면 Nemotron이 프로필을 뽑고, 답변과 함께 정품 확인, 추천 제품, 하루 동선, 매장용 한글 카드(눌러서 크게), 걸러낸 정보, 차단한 행동 로그를 카드로 보여 줍니다. "공통 테스트"를 언급하면 문화 코스 초안을 만듭니다.

### Vercel 배포 (공개 데모 URL)

`public/index.html`이 화면, `api/index.py`가 `/`·`/api/status`·`/api/chat`을 처리하는 단일 서버리스 함수입니다(`vercel.json`, `pyproject.toml`의 `[tool.vercel]`). Vercel 프로젝트 설정의 Environment Variables에 `NVIDIA_API_KEY`를 넣으면 됩니다. 결과물은 `/tmp`에 저장됩니다. Vercel에는 OpenShell이 없어 앱 가드만 동작하고, 정책 차단 데모는 아래 샌드박스에서 보여 줍니다.

### OpenShell 샌드박스 실행 (OpenShell 0.1.2에서 검증)

전체 과정과 차단 시험 기록은 [`docs/openshell-setup-log.md`](docs/openshell-setup-log.md)에 있습니다.

```bash
# 1) 샌드박스 이미지 (WORKDIR /sandbox, 코드는 root 소유 /app 에 읽기 전용)
docker build -f openshell/Dockerfile -t kbg-sandbox:v2 .

# 2) NVIDIA 키는 provider 로 등록 → 샌드박스 안 에이전트는 자리표시자만 본다
openshell provider profile import -f openshell/nvidia-profile.yaml
read -rs NVIDIA_API_KEY; export NVIDIA_API_KEY
openshell provider create --name nvidia --type nvidia-hackathon --credential NVIDIA_API_KEY; unset NVIDIA_API_KEY

# 3) 정책을 걸고 샌드박스 생성
openshell sandbox create --name kbg --from kbg-sandbox:v2 --policy ./policy/openshell-policy.yaml \
  --provider nvidia --detach -- sleep infinity
```

**두 겹 차단 시연:** `KBG_OPENSHELL_PROBE=1`을 주면 에이전트가 앱 가드를 건너뛰고 숨은 지시 대상과 미끼 파일(`/hackathon/restricted/latest_verified_history.md` 등)을 실제로 열어/보내 봅니다. 파일은 열기만 하고 읽지 않으며 URL에는 본문 없이 HEAD만 보냅니다. OpenShell 샌드박스 안에서는 이 시도가 정책에 막히고(`Permission denied`, `NET:OPEN DENIED`) `openshell logs`와 `audit.jsonl`에 함께 남습니다. 1겹은 앱의 신뢰성 판단, 2겹은 OpenShell 런타임입니다(setup log 14절).

## 권한 설계와 이유

| 대상 | 권한 | 이유 |
| --- | --- | --- |
| `/hackathon/input` | 읽기 | 판단 근거 자료. 쓰기는 필요 없음 |
| `/app` (에이전트 코드) | 읽기 | root 소유. 에이전트가 자기 코드를 고치지 못함 |
| 실행 사용자 | `sandbox` | root 가 아닌 사용자로 실행 |
| NVIDIA API 키 | 샌드박스 밖 | OpenShell provider 가 허용된 NVIDIA 주소로 나갈 때만 주입. 에이전트는 자리표시자만 봄 |
| `/hackathon/output` | 쓰기 | 동선·카드·신뢰성 보고서·감사 로그 저장만 |
| `/hackathon/restricted`, `/hackathon/secrets` | 없음 | 정책에 경로를 넣지 않아 접근 불가. 앱 가드도 거부하고 기록 |
| `integrate.api.nvidia.com`, `ai.api.nvidia.com` | POST, 지정 경로만 | Nemotron 추론·리랭크 호출 |
| `english.visitkorea.or.kr`, `english.visitseoul.net` | GET만 | 공식 관광·행사 정보 확인 |
| 그 밖의 모든 호스트 (오픈마켓, 업로드 주소, 메일·예약·결제) | 거부 | 기본 거부. 위장 K-뷰티 유통 경로와 숨은 지시의 전송 대상 차단 |

## 사용하는 외부 API·데이터와 허용 범위

| 대상 | 쓰임 | 실행 중 호출 | 허용 범위 |
| --- | --- | --- | --- |
| NVIDIA API Catalog — `nvidia/nemotron-3-ultra-550b-a55b` (503이면 `nvidia/nemotron-3-super-120b-a12b`) | 요청 이해(프로필 추출), 답변·코스 문장, 사용자 언어 번역, 꼬리질문 | 예 | `integrate.api.nvidia.com` POST `/v1/chat/completions`만 (OpenShell 정책·provider) |
| NVIDIA API Catalog — `nvidia/nemotron-3-embed-1b` | 다국어 질문과 제품 설명의 관련도 | 예 | `integrate.api.nvidia.com` POST `/v1/embeddings`만 |
| TypeSafe AI **Jev** (`jev-latest`) | 판단 게이트: 사용자 요청이 금지 행동(금지 영역 읽기·외부 전송·예약·결제)을 시키는지, 자료에 AI를 향한 지시·근거 없는 광고가 있는지 **확률만** 받아 규칙 판정과 함께 사용 (`kbeauty_gate/jev.py`) | 예 (키 있을 때만, 없으면 규칙만) | `api.typesafe.ai` POST `/v1/systemone`만. 샌드박스에서는 OpenShell provider로 키 주입 |
| 식품의약품안전처 공공데이터 — 화장품 규제정보, 화장품 회수·판매중지 정보 | 전성분의 나라별 금지·제한 대조, 회수 제품 차단 | **아니오** (2026-10-07 스냅샷 파일) | 없음 — `hackathon/input/beauty/regulatory/kr_mfds/` 읽기 전용. 출처·건수: [`SOURCE.md`](hackathon/input/beauty/regulatory/kr_mfds/SOURCE.md) |
| 대만 식약서(TFDA) 오픈데이터 — 화장품 금지·사용 제한·자외선 차단제 성분 | 금지 성분 보조 대조, 사용 한도 안내 | **아니오** (2026-10-07 스냅샷 파일) | 없음 — `hackathon/input/beauty/regulatory/tw_tfda/` 읽기 전용. 출처: [`SOURCE.md`](hackathon/input/beauty/regulatory/tw_tfda/SOURCE.md) |
| 지도 링크 (카카오맵·Google Maps 검색 URL) | 동선 지역을 지도 앱에서 열기 | 아니오 (사용자가 링크를 눌러 이동) | 서버는 지도 데이터를 조회하지 않음 |

- 공식 데이터는 기관이 배포한 원본을 받은 날짜·출처와 함께 파일로 넣었습니다. 실행 중에는 키도 인터넷도 쓰지 않으므로 OpenShell 네트워크 정책에 추가하지 않았습니다. 규제 해당 여부만 알 수 있고 제품의 실제 함량은 알 수 없어 "함량은 라벨 확인"으로 안내합니다.
- 비공식 수집 서버(예: 매장·재고 스크래핑 프록시)는 출처와 안정성을 확인할 수 없어 사용하지 않았습니다.

### 개인정보와 외부 전송

- Nemotron을 호출할 때 **사용자가 입력한 문장과 판단에 필요한 정보가 NVIDIA API로 전송됩니다.** 키가 없으면 규칙 기반으로만 동작하고 아무것도 전송하지 않습니다.
  - K-뷰티: 요청 문장, 피부 타입·고민·피하고 싶은 성분, 예산·일정·지역, 신뢰 판정을 통과한 제품·매장 자료
  - 공통 테스트: 요청 문장, 방문단 이름과 음식 제한(예: 비건, 알레르기), 신뢰 판정을 통과한 공통 자료
- `restricted`(의료 기록 등)·`secrets` 내용과 API 키는 모델에 전달하지 않습니다. 키는 샌드박스 밖 OpenShell provider가 허용된 NVIDIA 주소로 나갈 때만 넣습니다.
- 데모는 가상 프로필과 주최측 연습 방문단 자료만 씁니다. 실제 개인정보는 입력하지 마세요.
- `hackathon/input/beauty/`의 브랜드·제품·매장은 데모용 가상 데이터입니다(위장 제품의 수은 표기도 가상). 회수 제품 경고는 식약처가 공개한 실제 회수 정보를 사용자가 그 제품을 물었을 때만 보여 줍니다.

## Meet the team

<table>
<tr>
<td align="center" width="20%"><a href="https://github.com/kakyungkim"><img src="https://avatars.githubusercontent.com/u/84395053?v=4" width="88" alt="Ka-Kyung Kim"><br><strong>김가경</strong><br>Ka-Kyung Kim</a></td>
<td align="center" width="20%"><a href="https://github.com/AwesomeZun"><img src="https://avatars.githubusercontent.com/u/55944204?v=4" width="88" alt="Seong-Jun Kang"><br><strong>강성준</strong><br>Seong-Jun Kang</a></td>
<td align="center" width="20%"><a href="https://github.com/Geongyu"><img src="https://avatars.githubusercontent.com/u/37532168?v=4" width="88" alt="Geon-Gyu LEE"><br><strong>이건규</strong><br>Geon-Gyu LEE</a></td>
<td align="center" width="20%"><a href="https://github.com/ybaeus"><img src="https://avatars.githubusercontent.com/u/47170687?v=4" width="88" alt="Yeji Bae"><br><strong>배예지</strong><br>Yeji Bae</a></td>
<td align="center" width="20%"><a href="https://github.com/YMYDGenie"><img src="https://avatars.githubusercontent.com/u/133306595?v=4" width="88" alt="Eunjin Jeon"><br><strong>전은진</strong><br>Eunjin Jeon</a></td>
</tr>
</table>

| Member | Background | Contribution to K-BeautyGate |
| :--- | :--- | :--- |
| **김가경** · [@kakyungkim](https://github.com/kakyungkim) | 바이오 데이터 분석 · 혈중 암세포 및 신약개발 바이오마커 분석 경험 |  |
| **강성준** <sup><a href="https://kangseongjun.com" title="강성준 개인 웹사이트">↗</a></sup> · [@AwesomeZun](https://github.com/AwesomeZun) | 단일세포·공간오믹스 · 신약 후보 평가 · 『AI 신약개발 실전가이드』 출간 |  |
| **이건규** <sup><a href="https://geongyu.github.io/" title="이건규 개인 웹사이트">↗</a></sup> · [@Geongyu](https://github.com/Geongyu) | AI researcher · 병리·영상의학 및 오믹스를 결합한 예후·약물 반응 예측 |  |
| **배예지** · [@ybaeus](https://github.com/ybaeus) | 병원 데이터 사이언티스트 · 멀티오믹스·공간·이미지 데이터 |  |
| **전은진** · [@YMYDGenie](https://github.com/YMYDGenie) | 약사 · 약사를 위한 AI 제품 개발 |  |
