# 토끼 채팅 화면 (Muse 스타일)

K-BeautyGate 에이전트를 토끼 캐릭터와 대화하는 웹앱 화면으로 보여 줍니다. 공개 데모의 첫 화면입니다. `/`는 [vercel.json](../../vercel.json)에서 `/bunny`로 이동하고, 이전 화면은 `/index.html`에 남아 있습니다.

- 같은 API(`/api/chat`)를 씁니다. 추천, 정품 확인, 동선, 직원용 한국어 카드, 문화 코스와 음식 카드, 5개 언어, 고른 언어 우선, 후속 질문을 모두 보여 줍니다.
- 경로, 파일명, 보호 폴더 이름, 모델·인프라 이름 같은 개발 용어는 화면에 내보내지 않고 쉬운 말로 바꿉니다. 기술 기록은 `/bunny?backstage=1` 에서만 보입니다.
- 화면 구성: 대화 · 계획 · 카드 · 안심 탭, 제품 상세 시트, 크게 보기 카드, 음성 입력(지원 브라우저).

## 수정과 빌드

`bunny.src.html` 을 고친 뒤 아래 명령으로 `public/bunny.html` (그림을 넣은 단일 파일)을 다시 만듭니다.

```bash
python3 ui/bunny/build.py
node --test tests/bunny_ui.test.cjs
```

`art/` 의 그림은 팀 캐릭터를 참고로 GPT-image-2로 만든 뒤 WebP로 줄인 것입니다.

## Vercel 배포 (토끼 화면을 첫 화면으로)

공용 `vercel.json`은 그대로 두고, 배포할 때만 `vercel.bunny.json`을 씁니다. 이 설정은 `/`를 `/bunny`로 보냅니다.

```bash
vercel deploy --prod --local-config vercel.bunny.json
```

- Vercel 프로젝트의 Framework Preset은 Python이어야 `/api/*`가 동작합니다.
- 모델 답변에는 Production 환경변수 `NVIDIA_API_KEY`가 필요하고, 판단 모델을 쓰려면 `TYPESAFE_API_KEY`도 넣습니다. 환경변수를 바꾼 뒤에는 다시 배포해야 반영됩니다.
