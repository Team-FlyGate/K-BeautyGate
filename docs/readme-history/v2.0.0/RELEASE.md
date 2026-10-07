# README visual v2.0.0

2026-10-07 · Documentation and image update

K-BeautyGate의 소개를 사용자 요청 → 쇼핑 계획과 한국어 카드 → 실행 구조 → 원본 증거 → 실행 방법 순서로 구성했습니다. 공개 웹 체험과 Brev의 OpenShell 실행 기록을 구분합니다.

## 기준 자료

- 구현 확인 기준: `8871a548d306037a2d7346356ffcb6aed5a8362b`.
- 이전 README 원문: [v1.0.0 보존본](../v1.0.0/README.md). 시작 시점 `10b17ed`의 내용을 그대로 보존했습니다. 보존본 내부의 상대 링크는 당시 저장소 루트 기준입니다.
- 이 버전의 고정 문서: [README v2.0.0](README.md).
- OpenShell 증거: [기존 Brev 실행](../../../evidence/run_beauty_0551/). 이 문서 작업에서 Brev 샌드박스를 새로 실행하지는 않았습니다.

## 이미지

| 파일 | 출처와 의미 |
| --- | --- |
| [Hero](../../images/kbeautygate-hero_v2.0.0.png) | AI 생성 콘셉트 아트. 한복 토끼와 한국의 문을 모티프로 제작. 실제 UI·제품 사진이 아님 |
| [Architecture](../../images/kbeautygate-architecture_v2.0.0.png) | AI로 작성한 구조 설명 그림. 코드와 실행 기록을 대조해 검토. 외부 모델 API와 샌드박스 경계를 구분 |
| [Welcome](../../images/kbeautygate-web-welcome_v2.0.0.png) | 2026-10-07 공개 웹 데모, 일본어 브라우저 설정, 1440 × 1080 |
| [Korean staff card](../../images/kbeautygate-staff-card_v2.0.0.png) | 공개 웹 API의 실제 응답으로 생성한 한국어 카드 확대 화면, 1440 × 1080 |
| [Shopping result](../../images/kbeautygate-shopping-result_v2.0.0.png) | 동일한 실제 응답을 수정 없이 재생해 전체 결과 영역을 촬영. 긴 화면의 잘림을 피하기 위해 큰 뷰포트 사용 |

공개 API 호출은 HTTP 200, beauty 모드, 추천 4개를 반환했습니다. 해당 응답은 일본어 설명을 완성하지 못했다는 안내도 포함하며, 캡처에 그대로 남겼습니다. 이 확인은 한 요청의 동작 확인이며 전체 번역 품질이나 처리 속도 벤치마크가 아닙니다.

## 확인

- Python 검사: 88개 통과. 기존 데이터 검사에서 파일 핸들 관련 ResourceWarning 2건 발생.
- 프런트엔드 검사: 60개 통과.
- 키 없는 CLI 실행: 쇼핑 계획, 직원용 카드, trust report, audit 파일 생성 확인.
- GitHub Markdown 렌더링, 이미지 표시, 내부 링크와 섹션 이동 확인.
- 애플리케이션 코드·정책·기존 실행 증거는 이 문서 변경에 포함하지 않았습니다.

실행 증거는 시험한 경로와 호스트에 한정합니다. 현재 Dockerfile의 데이터 사본 경로와 best-effort 파일 격리 설정, 선택적 Jev 연결의 별도 네트워크 설정은 README의 검증 범위에 명시했습니다.
