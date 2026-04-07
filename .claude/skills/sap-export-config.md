---
name: sap-export-config
description: SAP 내보내기 Excel의 컬럼 매핑, 수식, 데이터 입력 규칙을 변경합니다.
---

# SAP 내보내기 설정 변경

SAP용 Excel 생성 시 컬럼 매핑이나 수식을 변경할 때 이 skill을 사용합니다.

## 설정 파일 구조

### `static/sap_upload_formulas.json`
SAP Excel의 각 컬럼에 대한 데이터 입력 규칙과 수식을 정의합니다.

```json
{
  "dataInputColumns": [
    {
      "column": "C",           // Excel 컬럼 문자
      "byForm": {
        "01": { "field": "受注先コード" },  // 양식 01: 이 필드값을 넣음
        "02": { "field": "受注先コード" },
        ...
      }
    },
    {
      "column": "T",           // 수량 컬럼 (양식별 다름)
      "byForm": {
        "01": {                // 조건부 매핑
          "cond": [
            { "if_field": "数量単位", "if_eq": "個", "then_field": "数量" },
            { "if_field": "数量単位", "if_eq": "CS", "then_expr": "入数*数量" }
          ]
        },
        "02": { "field": "取引数量計" },   // 단순 매핑
        "03": { "field": "バラ" },
        "04": { "field": "対象数量又は金額" },
        "05": ""                           // 빈값
      }
    }
  ],
  "excelFormulaColumns": [
    {
      "column": "U",
      "formula": "=P3*N3 + R3*O3 + T3",   // Excel 수식 (행 번호는 자동 조정)
      "description": "P×N + R×O + T"
    }
  ]
}
```

### `config/form_types.json` 연관 설정
- `sap_quantity`: SAP Column T에 매핑되는 설정 (form_types.json과 sap_upload_formulas.json의 Column T를 동기화)
- `sap_extra_columns`: P, R 등 양식별 추가 컬럼 (예: 03번의 ケース/バラ)
- `fields.final_amount`: SAP Column AL에 매핑

## 수정 시 체크포인트

### 1. 데이터 입력 컬럼 변경
`static/sap_upload_formulas.json`의 `dataInputColumns` 수정:

**단순 필드 매핑 추가/변경:**
```json
{ "field": "필드명" }
```

**조건부 매핑 추가/변경:**
```json
{
  "cond": [
    { "if_field": "조건필드", "if_eq": "비교값", "then_field": "결과필드" },
    { "if_field": "조건필드", "if_eq": "비교값2", "then_expr": "계산식" }
  ]
}
```

**빈�� (해당 양식에서 사용 안 함):**
```json
""
```

### 2. Excel 수식 컬럼 변경
`excelFormulaColumns` 수정:
- `formula`: Excel 수식 (예: "=P3*N3 + R3*O3 + T3")
- 행 번호 3은 기준값이며, 백엔드에서 실제 행 번호로 자동 치환

### 3. 동기화 확인
- `config/form_types.json`의 `sap_quantity`와 `sap_upload_formulas.json` Column T가 일치하는지
- `config/form_types.json`의 `fields.final_amount`와 Column AL이 일치하는지
- `config/form_types.json`의 `sap_extra_columns`와 실제 컬럼 매핑이 일치하는지

### 4. 백엔드 처리 확인
`backend/api/routes/sap_upload.py`의 `process_item_for_sap()`:
- JSON config를 읽어 각 컬럼의 값을 item_data에서 추출
- `cond` 타입은 조건 체이닝으로 처리
- `then_expr`은 eval이 아닌 안전한 파싱으로 처리 (현재 "입수*수량" 패턴만 지원)

## 테스트

1. 해당 양식의 문서가 이미 업로드되어 있는지 확인
2. SAP Upload 탭에서 Excel 내보���기 실행
3. 생성된 Excel 파일의 변경된 컬럼 값이 올바른지 확인
4. Excel 수식 셀이 정상 계산되는지 확인
