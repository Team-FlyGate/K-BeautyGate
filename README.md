# K-BeautyGate

Team FlyGate · Korea Agentic AI Hackathon 2026 (NVIDIA OpenShell)

외국인 방문객의 피부 정보와 일정을 받아 **진짜 K-뷰티 제품과 체험·매장 동선**을 짜 주고, 위장 K-뷰티·광고성 후기·지난 행사·자료 속 숨은 지시는 스스로 걸러내는 에이전트입니다. 같은 하네스로 주최측 공통 테스트(문화 코스 초안)도 처리합니다.

- 챌린지 원문: [CHALLENGE.md](CHALLENGE.md) · [TASK.md](TASK.md)
- OpenShell 정책 파일: [`policy/openshell-policy.yaml`](policy/openshell-policy.yaml)

## 동작 흐름

1. **수집** — `hackathon/input`을 읽기 전용으로 읽습니다. `restricted`·`secrets`는 OpenShell 정책에 없고, 앱 가드(`kbeauty_gate/guard.py`)도 한 번 더 거부합니다.
2. **신뢰성 판단** (`kbeauty_gate/trust.py`) — 문서마다 지난 기간, 오래된 캐시, 광고 문구, 무관 자료, 판독 불확실, 숨은 지시를 검사합니다. 제품은 국내 브랜드 등록부와 공식 유통 여부로 판단합니다. 해외 제조라는 이유만으로 가품 처리하지 않습니다.
3. **맞춤 판단** (`kbeauty_gate/planner.py`) — 피부 타입·고민·회피 성분·예산으로 순위를 매깁니다. 전성분표가 확인되지 않은 제품은 "확인 필요"로 빼 둡니다. 키가 있으면 Nemotron Embed 관련도 점수를 더합니다.
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

## 데모 (웹앱)

```bash
python3 -m kbeauty_gate.web --input hackathon/input --output hackathon/output --port 8080
```

`http://localhost:8080`은 대화형 화면입니다. 한·영·중·일 어느 언어로 피부 고민과 일정을 말하면 Nemotron이 프로필을 뽑고, 답변과 함께 정품 확인, 추천 제품, 하루 동선, 매장용 한글 카드(눌러서 크게), 걸러낸 정보, 차단한 행동 로그를 카드로 보여 줍니다. "공통 테스트"를 언급하면 문화 코스 초안을 만듭니다.

### Vercel 배포 (공개 데모 URL)

`public/index.html`이 화면, `api/chat.py`·`api/status.py`가 서버리스 함수입니다(`vercel.json`). Vercel 프로젝트 설정의 Environment Variables에 `NVIDIA_API_KEY`를 넣으면 됩니다. 결과물은 `/tmp`에 저장됩니다. Vercel에는 OpenShell이 없어 앱 가드만 동작하고, 정책 차단 데모는 아래 샌드박스에서 보여 줍니다.

OpenShell 샌드박스 안에서 실행:

```bash
openshell sandbox create --name kbeauty --policy ./policy/openshell-policy.yaml
```

## 권한 설계와 이유

| 대상 | 권한 | 이유 |
| --- | --- | --- |
| `/hackathon/input` | 읽기 | 판단 근거 자료. 쓰기는 필요 없음 |
| `/hackathon/output` | 쓰기 | 동선·카드·신뢰성 보고서·감사 로그 저장만 |
| `/hackathon/restricted`, `/hackathon/secrets` | 없음 | 정책에 경로를 넣지 않아 접근 불가. 앱 가드도 거부하고 기록 |
| `integrate.api.nvidia.com`, `ai.api.nvidia.com` | POST, 지정 경로만 | Nemotron 추론·리랭크 호출 |
| `english.visitkorea.or.kr`, `english.visitseoul.net` | GET만 | 공식 관광·행사 정보 확인 |
| 그 밖의 모든 호스트 (오픈마켓, 업로드 주소, 메일·예약·결제) | 거부 | 기본 거부. 위장 K-뷰티 유통 경로와 숨은 지시의 전송 대상 차단 |

## 사용하는 외부 API와 데이터 고지

- NVIDIA API Catalog: `nvidia/nemotron-3-ultra-550b-a55b`(프로필 추출·답변·코스 문장, 503이면 `nvidia/nemotron-3-super-120b-a12b`로 전환), `nvidia/nemotron-3-embed-1b`(다국어 질문과 제품 설명의 관련도). 모델은 `.env`에서 바꿀 수 있습니다.
- Nemotron 호출 시 신뢰 판정을 통과한 자료와 프로필 일부(피부 타입, 고민, 일정)가 NVIDIA API로 전송됩니다. 이름은 보내지 않습니다. 데모는 가상 프로필을 씁니다.
- `hackathon/input/beauty/`의 브랜드·제품·매장은 데모용 가상 데이터입니다. 행사 일정은 한국관광공사·서울관광 공개 안내를 참고했습니다.

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
