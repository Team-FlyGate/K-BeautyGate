# 식품의약품안전처(MFDS) 화장품 공공데이터 스냅샷

공공데이터포털 Open API 응답을 그대로 저장했다. 에이전트는 실행 중 키나 인터넷 없이 이 파일만 읽는다(인증키는 저장하지 않음).

| 파일 | API | 엔드포인트 | 건수 |
| --- | --- | --- | --- |
| regulation.json | 식품의약품안전처_화장품 규제정보 (성분 표준명·영문명, 금지 국가, 제한 국가) | `1471000/CsmtcsReglMaterialInfoService/getCsmtcsReglMaterialInfoService` | 7,257 |
| recall.json | 식품의약품안전처_화장품 회수·판매중지 정보 | `1471000/CsmtcsRtrvlSleStpgeInfo/getCsmtcsRtrvlSleStpgeInfo` | 29 |

- 받은 날짜: 2026-10-07 14:41 KST (https://apis.data.go.kr, data.go.kr 개발계정)
- 금지·제한 국가: 한국, 중국, 일본, 미국, 대만, EU, 아세안, 캐나다, 브라질, 아르헨티나
- 주의: 규제 해당 여부만 알려 주며 제품의 실제 함량은 알 수 없다. 회수 목록은 받은 시점 기준이다.
- 함께 신청한 API(기능성화장품 보고·심사품목, 화장품 제조판매업 정보)는 건수가 커서(약 2만~20만 건) 오늘은 저장하지 않았다.
