---
name: modify-form-config
description: 기존 양식 타입의 필드명, NET 계산 로직, SAP 매핑 등 설정을 변경합니다.
---

# 양식 설정 변경

기존 양식 타입(01~05)의 설정을 수정할 때 이 skill을 사용합니다.

## 변경 가능 항목

| 항목 | 설정 위치 | 영향 범위 |
|------|----------|----------|
| **필드명** (조건/금액) | `config/form_types.json` → `fields` | 그리드 컬럼 순서, NET 계산, SAP 내보내기 |
| **NET 계산 방식** | `config/form_types.json` → `net_calculation` | 그리드 NET 셀, NET 경고(노란색 행) |
| **소수점 변환** | `config/form_types.json` → `decimal_conversion` | 백엔드 후처리 (미수조건 값 변환) |
| **행 병합** | `config/form_types.json` → `row_merging` | 백엔드 후처리 (02번 행 병합) |
| **SAP 수량** | `config/form_types.json` → `sap_quantity` | SAP Excel Column T 값 |
| **SAP 컬럼 매핑** | `static/sap_upload_formulas.json` | SAP Excel 전체 컬럼 |
| **고객코드 조회** | `config/form_types.json` → `use_customer_lookup` | 단가 모달 domae API 호출 |
| **자동추론 키** | `config/form_types.json` → `inference_keys` | 양식 타입 자동 감지 |
| **라벨** | DB `form_type_labels` 또는 `config/form_types.json` → `label` | UI 표시명 |

## 수정 절차

### 1. `config/form_types.json` 수정
해당 양식 코드(예: "03")의 원하는 필드를 변경합니다.

**필드명 변경 예시** (03번의 금액 필드��을 바꿀 때):
```json
"03": {
  "fields": {
    "amount1": "請求金額",     // ← 변경할 값
    "amount2": "請求金額2",    // ← 변경할 값
    "final_amount": "最終請求金額"  // ← 변경할 값
  }
}
```

**NET 계산 방식 변경 예시**:
```json
"net_calculation": {
  "type": "dual_condition_sum",         // "default" 또는 "dual_condition_sum"
  "formula": "仕切 - (condition1 + condition2)"  // dual일 때만
}
```

### 2. `static/sap_upload_formulas.json` 동기화 (필드명 변경 시)
`dataInputColumns`의 해당 양식 `byForm` 값을 JSON의 fields와 일치시킵니다:
- Column AL → `final_amount` 필드와 일치
- Column T → `sap_quantity` 설정과 일치
- Column P/R → `sap_extra_columns`와 일치

### 3. 영향도 체크
변경 후 아래 기능이 정상 작동하는지 확인:

- **그리드 금액 컬럼 순서**: `useItemsGridColumns.tsx`에서 `getAmountLayout()` → JSON의 fields 사용
- **NET 계산**: `useItemsGridColumns.tsx` + `ItemsGridRdg.tsx`에서 `getNetConditionFields()` → JSON의 net_calculation 사용
- **소수점 변환**: `form04_mishu_utils.py`에서 `get_form_types_config()` → JSON의 decimal_conversion 사용
- **양식 추론**: `form2_rebate_utils.py`의 `infer_form_type_from_item()` → JSON의 inference_keys 사용
- **SAP 내보내기**: `backend/api/routes/sap_upload.py` → `static/sap_upload_formulas.json` 사용

## 참고: 코드 수정이 필요한 경우

JSON만으로 처리할 수 없는 변경:
- **새로운 NET 계산 type 추가**: `useFormTypesConfig.ts`의 `getNetConditionFields()`와 프론트엔드 렌더링 로직 수정 필요
- **새로운 행 병합 패턴**: `form2_rebate_utils.py`의 `_merge_form2_rows_by_condition()` 수정 필요 (현재 form02 전용 하드코딩)
- **새로운 소수점 변환 규칙**: `form04_mishu_utils.py`의 변환 로직 수정 필요 (현재 value/100 고정)
