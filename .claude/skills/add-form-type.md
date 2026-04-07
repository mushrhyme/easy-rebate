---
name: add-form-type
description: 새로운 양식 타입(form_type) 추가 시 필요한 전체 파일 수정을 안내하고 실행합니다.
---

# 새 양식 타입 추가

사용자가 새로운 양식 타입(예: 06번)을 추가하려 할 때 이 skill을 사용합니다.

## 사용자에게 먼저 확인할 정보

1. **양식 코드** (예: "06")
2. **라벨** (예: "条件⑥" 또는 커스텀 이름)
3. **조건 필드명** (condition1, condition2) — 예: "条件"/"条件2" 또는 고유 필드명
4. **금액 필드명** (amount1, amount2, final_amount) — 예: "金額"/"金額2"/"最終金額"
5. **NET 계산 방식**: `default`(단가 기반) 또는 `dual_condition_sum`(条件1+条件2 합산)
6. **소수점 변환 필요 여부** (decimal_conversion) — 03/04처럼 value/100 변환이 필요한지
7. **행 병합 규칙** (row_merging) — 02처럼 특정 조건의 행을 이전 행에 병합하는지
8. **SAP 수량 필드** — SAP Column T에 매핑할 필드 (조건부/단일 필드/없음)
9. **고객코드 조회 사용 여부** (use_customer_lookup) — 01/03처럼 domae API 조회 대상인지
10. **자동추론 키** (inference_keys) — LLM 결과에서 이 양식을 식별하는 고유 키

## 수정 파일 목록 (순서대로)

### 1. `config/form_types.json` — 양식 설정 추가
기존 양식(01~05) 구조를 참고하여 새 양식 블록 추가:
```json
"06": {
  "label": "...",
  "fields": { "condition1": "...", "condition2": "...", ... },
  "net_calculation": { "type": "..." },
  "decimal_conversion": null,
  "row_merging": null,
  "sap_quantity": { "type": "field", "field": "..." },
  "sap_extra_columns": {},
  "use_customer_lookup": false,
  "inference_keys": ["..."],
  "inference_priority": 0
}
```
- `inference_priority`: 낮을수록 우선 매칭. 기존 최소값(1)보다 작게 설정하면 최우선.

### 2. `static/sap_upload_formulas.json` — SAP 컬럼 매핑 추가
각 `dataInputColumns` 항목의 `byForm`에 새 양식 코드 추가:
- Column T: 수량 필드 매핑
- Column AL: final_amount 필드 매핑
- 기타 컬럼: 공통 필드는 기존과 동일하게, 양식 고유 필드가 있으면 추가

### 3. DB `form_type_labels` — 라벨 등록
```sql
INSERT INTO form_type_labels (form_code, display_name, updated_at)
VALUES ('06', '사용자가 지정한 라벨', CURRENT_TIMESTAMP)
ON CONFLICT (form_code) DO UPDATE SET display_name = EXCLUDED.display_name;
```
또는 API 호출: `POST /api/form-types` body: `{ "form_code": "06", "display_name": "..." }`

### 4. 특수 로직이 필요한 경우 (선택)
- **decimal_conversion 추가**: `modules/utils/form04_mishu_utils.py`의 guard_keys는 JSON에서 자동 로드됨. JSON에만 설정하면 됨.
- **row_merging 추가**: `modules/utils/form2_rebate_utils.py`의 병합 로직 확장 필요 (현재 form02 전용). JSON의 `row_merging` 설정을 읽어 동적 처리하려면 코드 수정 필요.
- **프롬프트 분리**: 양식별 전용 프롬프트가 필요하면 `prompts/` 디렉토리에 추가하고 `modules/utils/config.py`에서 form_type별 선택 로직 추가.

## 검증

1. 백엔드: `GET /api/form-types/config` 응답에 새 양식이 포함되는지 확인
2. 프론트엔드: 업로드 시 양식 선택 드롭다운에 표시되는지 확인
3. 그리드: 금액 필드 순서와 NET 계산이 올바른지 확인
4. SAP 내보내기: 새 양식 문서로 Excel 생성 테스트
