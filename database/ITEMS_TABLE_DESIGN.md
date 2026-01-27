# Items 테이블 설계 문서

## 개요

행 단위 동시 편집과 충돌 방지를 위한 최적화된 데이터베이스 구조 설계

## 핵심 요구사항

1. ✅ **개별 행 수정**: 한 행만 수정해도 다른 행에 영향 없음
2. ✅ **동시성 제어**: 여러 사용자가 다른 행을 동시에 편집 가능
3. ✅ **양식지별 차이 수용**: 양식지별로 필드명과 컬럼 수가 다름
4. ✅ **검색 성능**: 자주 검색하는 필드는 인덱스 활용

## 공통 필드 선정 기준

공통 필드는 다음 두 조건을 모두 만족하는 필드만 컬럼으로 분리합니다:

1. **자주 검색/필터링되는 필드**: 검색 성능 최적화를 위해 B-tree 인덱스 활용
2. **모든 양식지(01~05)에 공통으로 존재하는 필드**: 스키마 일관성 유지

**선정된 공통 필드:**
- `customer` (거래처명): 모든 양식지에 존재, 자주 검색됨
- `product_name` (상품명): 모든 양식지에 존재, 자주 검색됨

**일반 컬럼으로 저장되는 필드 (고정 구조):**
- `first_review_checked`, `second_review_checked`: 검토 상태 (고정 구조이므로 JSONB 대신 일반 컬럼 사용)
- `first_reviewed_at`, `second_reviewed_at`: 검토 일시

**JSONB로 저장되는 필드 (가변 구조):**
- `customer_code`, `amount`, `quantity`, `units_per_case`, `case_count`, `bara_count` 등
- 양식지별로 필드명이 다르거나 모든 양식지에 존재하지 않는 필드
- 예: `請求伝票番号`, `計上日`, `期間開始`, `期間終了`, `条件`, `条件区分`, `条件備考`, `消費税率`, `備考`, `タイプ` 등

---

## 테이블 구조

### 1. items 테이블 (행 단위 데이터)

```sql
CREATE TABLE items (
    -- 기본 키
    item_id SERIAL PRIMARY KEY,
    
    -- 식별자
    pdf_filename VARCHAR(500) NOT NULL,
    page_number INTEGER NOT NULL,
    item_order INTEGER NOT NULL CHECK (item_order > 0),  -- UI 정렬용 순서 (논리적 식별은 item_id만 사용)
    
    -- 공통 필드 (자주 검색/필터링하는 필드만 컬럼으로)
    -- 양식지별로 필드명이 다르지만 의미는 동일 → 통일된 컬럼명 사용
    -- 선정 기준: 1) 자주 검색되는 필드, 2) 모든 양식지(01~05)에 공통으로 존재하는 필드
    customer VARCHAR(255),           -- 거래처명 (得意先名/得意先様/得意先 → 통일)
    product_name VARCHAR(500),       -- 상품명 (商品名 → 통일)
    
    -- 검토 상태 (고정 구조이므로 일반 컬럼 사용)
    -- JSONB는 가변 구조에만 사용하는 것이 원칙
    first_review_checked BOOLEAN DEFAULT FALSE,
    second_review_checked BOOLEAN DEFAULT FALSE,
    first_reviewed_at TIMESTAMP,
    second_reviewed_at TIMESTAMP,
    
    -- 양식지별 차이 필드 (원본 필드명 유지, JSONB로 저장)
    -- 예: 請求伝票番号, 計上日, 期間開始, 期間終了, 条件, 条件区分, 条件備考, 消費税率, 備考, タイプ 등
    item_data JSONB NOT NULL,
    
    -- 메타데이터
    version INTEGER NOT NULL DEFAULT 1,  -- 낙관적 락용 버전 (동시 수정 충돌 방지 필수)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- 제약조건
    -- UNIQUE 제약조건 제거: item_order는 UI 정렬용이므로 삽입/삭제/reorder 시 유연성 필요
    -- 논리적 식별은 item_id만 사용
    FOREIGN KEY (pdf_filename, page_number) 
        REFERENCES page_data(pdf_filename, page_number) 
        ON DELETE CASCADE
);
```

### 2. 인덱스

```sql
-- 기본 인덱스
CREATE INDEX idx_items_pdf_page ON items(pdf_filename, page_number);
CREATE INDEX idx_items_pdf_page_order ON items(pdf_filename, page_number, item_order);

-- 검색 최적화 인덱스 (공통 필드)
CREATE INDEX idx_items_customer ON items(customer);  -- 거래처 검색용
CREATE INDEX idx_items_product ON items(product_name);  -- 상품명 검색용

-- 검토 상태 인덱스 (필터링 최적화)
CREATE INDEX idx_items_first_review ON items(first_review_checked);  -- 1차 검토 필터링용
CREATE INDEX idx_items_second_review ON items(second_review_checked);  -- 2차 검토 필터링용

-- JSONB 검색 최적화 인덱스 (양식지별 필드)
CREATE INDEX idx_items_data_gin ON items USING GIN (item_data);  -- JSONB 내부 검색용
```

### 3. item_locks 테이블 (행 단위 편집 락)

```sql
-- 행 단위 편집 락 (UI 제어용)
-- item_id 기준 락 (pdf/page/order 조합 아님)
CREATE TABLE item_locks (
    item_id INTEGER PRIMARY KEY REFERENCES items(item_id) ON DELETE CASCADE,
    locked_by VARCHAR(100) NOT NULL,  -- 세션 ID 또는 사용자 ID
    locked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- 락 획득 시각
    expires_at TIMESTAMP NOT NULL  -- 락 만료 시각 (TTL 필수)
);

-- 인덱스
CREATE INDEX idx_item_locks_expires_at ON item_locks(expires_at);  -- 만료된 락 정리용
CREATE INDEX idx_item_locks_locked_by ON item_locks(locked_by);  -- 특정 사용자의 락 조회용
```

**핵심 포인트:**
- ✅ **item_id 기준 락**: 논리적 식별자(item_id)로 락 관리
- ✅ **TTL 필수**: `expires_at`으로 세션 죽어도 자동 해제
- ✅ **별도 테이블**: 편집 히스토리/TTL/강제 해제 처리 용이
- ✅ **LEFT JOIN으로 즉시 표시**: UI에서 락 상태 즉시 확인 가능

### 4. page_data 테이블 (페이지 메타데이터)

```sql
-- page_data는 페이지 메타데이터만 저장 (items 제외)
CREATE TABLE page_data (
    page_data_id SERIAL PRIMARY KEY,
    pdf_filename VARCHAR(500) NOT NULL REFERENCES documents(pdf_filename) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    
    -- 페이지 메타데이터 (items 제외)
    page_role VARCHAR(50),  -- cover, detail, summary, reply
    page_meta JSONB,  -- document_meta, party, payment, totals 등 (items 제외)
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(pdf_filename, page_number)
);
```

---

## 데이터 저장 방식

### 저장 시 필드 분리 로직

```python
def save_item(item_dict: dict, form_type: str) -> dict:
    """
    item을 저장할 때 공통 필드와 양식지별 필드로 분리
    
    Args:
        item_dict: 원본 item 딕셔너리 (양식지별 필드명 포함)
        form_type: 양식지 번호 (01, 02, 03, 04, 05)
        
    Returns:
        {
            "customer": "...",  # 공통 필드 (컬럼)
            "product_name": "...",
            "item_data": {...}  # 양식지별 필드 (JSONB)
        }
    """
    # 공통 필드 매핑 (양식지별 필드명 → 통일된 컬럼명)
    # 선정 기준: 1) 자주 검색되는 필드, 2) 모든 양식지(01~05)에 공통으로 존재하는 필드
    field_mapping = {
        "customer": ["得意先名", "得意先様", "得意先", "取引先"],
        "product_name": ["商品名"],
    }
    
    # 공통 필드 추출
    common_fields = {}
    for common_name, possible_names in field_mapping.items():
        for possible_name in possible_names:
            if possible_name in item_dict:
                common_fields[common_name] = item_dict[possible_name]
                break
    
    # 양식지별 필드 추출 (공통 필드 제외)
    item_data = {}
    for key, value in item_dict.items():
        # 공통 필드가 아니고, review_status 관련 필드가 아니면 item_data에 포함
        if key not in field_mapping.values() and not key.startswith("review_"):
            item_data[key] = value
    
    # 검토 상태 필드 추출 (일반 컬럼으로 저장)
    review_status = item_dict.get("review_status", {})
    review_fields = {
        "first_review_checked": review_status.get("first_review", {}).get("checked", False) if isinstance(review_status, dict) else False,
        "second_review_checked": review_status.get("second_review", {}).get("checked", False) if isinstance(review_status, dict) else False,
        "first_reviewed_at": review_status.get("first_review", {}).get("reviewed_at") if isinstance(review_status, dict) and isinstance(review_status.get("first_review"), dict) else None,
        "second_reviewed_at": review_status.get("second_review", {}).get("reviewed_at") if isinstance(review_status, dict) and isinstance(review_status.get("second_review"), dict) else None,
    }
    
    return {
        **common_fields,
        **review_fields,
        "item_data": item_data
    }
```

### 저장 예시

**원본 데이터 (양식지 01):**
```json
{
  "請求伝票番号": "7690664",
  "得意先名": "ローソントウカイ",
  "得意先コード": "(1991474)",
  "計上日": "01/31",
  "期間開始": "01/01",
  "期間終了": "01/31",
  "商品名": "チャパゲティ",
  "ケース入数": "30",
  "数量": "120",
  "金額": "4,704",
  "消費税率": "8.00%",
  "備考": "栗田　康広"
}
```

**저장 후:**
```sql
-- items 테이블
item_id: 1
customer: "ローソントウカイ"  -- 컬럼 (공통 필드)
product_name: "チャパゲティ"  -- 컬럼 (공통 필드)
first_review_checked: false  -- 컬럼 (검토 상태)
second_review_checked: false  -- 컬럼 (검토 상태)
first_reviewed_at: NULL  -- 컬럼 (검토 일시)
second_reviewed_at: NULL  -- 컬럼 (검토 일시)
item_data: '{
  "請求伝票番号": "7690664",
  "得意先コード": "(1991474)",
  "計上日": "01/31",
  "期間開始": "01/01",
  "期間終了": "01/31",
  "ケース入数": "30",
  "数量": "120",
  "金額": "4,704",
  "消費税率": "8.00%",
  "備考": "栗田　康広"
}'::jsonb
```

---

## 개별 행 수정

### UPDATE 쿼리

```sql
-- 특정 행만 수정 (낙관적 락 적용)
UPDATE items 
SET 
    customer = '수정된 거래처',  -- 공통 필드 (컬럼)
    product_name = '수정된 상품명',  -- 공통 필드 (컬럼)
    first_review_checked = true,  -- 검토 상태 (컬럼, 빠름!)
    first_reviewed_at = CURRENT_TIMESTAMP,  -- 검토 일시
    item_data = jsonb_set(
        item_data, 
        '{請求伝票番号}', 
        '"12345"'::jsonb
    ),
    version = version + 1,  -- 버전 증가 (낙관적 락)
    updated_at = CURRENT_TIMESTAMP
WHERE item_id = 123
  AND version = 1;  -- 클라이언트가 마지막으로 읽은 버전과 일치해야 함

-- rowcount = 0이면 다른 사용자가 먼저 수정함 (충돌 발생)
```

### Python 코드

```python
def update_single_item(
    item_id: int,
    updates: dict,
    expected_version: int  # 클라이언트가 마지막으로 읽은 버전
) -> tuple[bool, str]:
    """
    개별 행 수정 (낙관적 락 적용)
    
    Args:
        item_id: 수정할 행 ID
        updates: {
            "customer": "...",  # 공통 필드
            "product_name": "...",  # 공통 필드
            "first_review_checked": True,  # 검토 상태 (컬럼)
            "second_review_checked": False,  # 검토 상태 (컬럼)
            "item_data": {...}  # 양식지별 필드 (JSONB)
        }
        expected_version: 클라이언트가 마지막으로 읽은 버전
        
    Returns:
        (success: bool, message: str)
        - success=True: 수정 성공
        - success=False: 충돌 발생 (다른 사용자가 먼저 수정함)
    """
    # 필드 분류
    common_fields = {}  # customer, product_name
    review_fields = {}  # first_review_checked, second_review_checked 등
    jsonb_updates = {}  # item_data
    
    for key, value in updates.items():
        if key in ["customer", "product_name"]:
            common_fields[key] = value
        elif key in ["first_review_checked", "second_review_checked", 
                     "first_reviewed_at", "second_reviewed_at"]:
            review_fields[key] = value
        elif key == "item_data":
            jsonb_updates[key] = value
    
    # UPDATE 쿼리 구성
    set_clauses = []
    params = []
    
    # 공통 필드
    for key, value in common_fields.items():
        set_clauses.append(f"{key} = %s")
        params.append(value)
    
    # 검토 상태 필드
    for key, value in review_fields.items():
        set_clauses.append(f"{key} = %s")
        params.append(value)
    
    # JSONB 필드
    for key, value in jsonb_updates.items():
        set_clauses.append(f"{key} = %s::jsonb")
        params.append(json.dumps(value, ensure_ascii=False))
    
    # 버전 증가 (낙관적 락)
    set_clauses.append("version = version + 1")
    set_clauses.append("updated_at = CURRENT_TIMESTAMP")
    
    params.append(item_id)
    params.append(expected_version)  # WHERE 조건에 version 추가
    
    sql = f"""
        UPDATE items 
        SET {', '.join(set_clauses)}
        WHERE item_id = %s
          AND version = %s  -- 낙관적 락: 버전이 일치해야만 수정 가능
    """
    
    # 실행
    cursor.execute(sql, params)
    
    # rowcount 확인
    if cursor.rowcount == 0:
        # 충돌 발생: 다른 사용자가 먼저 수정함
        return False, "다른 사용자가 먼저 수정했습니다. 페이지를 새로고침하고 다시 시도해주세요."
    else:
        # 수정 성공
        return True, "수정 완료"
```

---

## 행 순서 관리 (Reorder)

### 설계 원칙

- **논리적 식별**: `item_id`만 사용 (고유하고 불변)
- **UI 정렬용**: `item_order`는 단순히 정렬 순서만 나타냄
- **UNIQUE 제약조건 없음**: 삽입/삭제/reorder 시 유연성 확보

### 행 삽입

```python
def insert_item(
    pdf_filename: str,
    page_number: int,
    item_order: int,  # 삽입할 위치
    item_data: dict
) -> int:
    """
    행 삽입 (중간 삽입 가능)
    
    삽입 위치 이후의 모든 행의 item_order를 +1 증가시킴
    """
    with conn.begin():
        # 1. 삽입 위치 이후의 모든 행 item_order +1
        cursor.execute("""
            UPDATE items
            SET item_order = item_order + 1
            WHERE pdf_filename = %s
              AND page_number = %s
              AND item_order >= %s
        """, (pdf_filename, page_number, item_order))
        
        # 2. 새 행 삽입
        cursor.execute("""
            INSERT INTO items (pdf_filename, page_number, item_order, ...)
            VALUES (%s, %s, %s, ...)
        """, (pdf_filename, page_number, item_order, ...))
        
        return cursor.lastrowid
```

### 행 삭제

```python
def delete_item(item_id: int) -> bool:
    """
    행 삭제 (item_id로 삭제)
    
    삭제 후 뒤의 행들의 item_order를 재조정할 필요 없음
    (item_order는 정렬용이므로 빈 번호가 있어도 무방)
    """
    cursor.execute("DELETE FROM items WHERE item_id = %s", (item_id,))
    return cursor.rowcount > 0
```

### Reorder (일괄 업데이트)

```python
def reorder_items(
    pdf_filename: str,
    page_number: int,
    item_orders: List[Tuple[int, int]]  # [(item_id, new_order), ...]
) -> bool:
    """
    행 순서 재정렬 (batch UPDATE)
    
    Args:
        item_orders: [(item_id, new_order), ...] 리스트
    """
    with conn.begin():
        # 일괄 업데이트
        cursor.executemany("""
            UPDATE items
            SET item_order = %s
            WHERE item_id = %s
        """, [(order, item_id) for item_id, order in item_orders])
        
        return True
```

### 조회 시 정렬

```sql
-- 페이지의 모든 행 조회 (item_order로 정렬)
SELECT * FROM items
WHERE pdf_filename = 'document.pdf'
  AND page_number = 1
ORDER BY item_order;
```

### 장점

1. ✅ **유연한 삽입/삭제**: UNIQUE 제약조건 없어서 자유롭게 삽입/삭제 가능
2. ✅ **간단한 Reorder**: batch UPDATE로 한 번에 처리
3. ✅ **논리적 식별 분리**: `item_id`는 불변, `item_order`는 UI용
4. ✅ **빈 번호 허용**: 삭제 후 item_order에 빈 번호가 있어도 정렬에 영향 없음

---

## 동시성 제어 (락)

### 이중 락 메커니즘

1. **item_locks (비관적 락)**: 편집 중 UI 제어용
   - 편집 시작 시 락 획득 → 다른 사용자에게 "편집 중" 표시
   - 편집 완료 시 락 해제
   - **한계**: 저장 시점 충돌 방지는 안 됨

2. **version (낙관적 락)**: 저장 시점 충돌 방지 (필수)
   - 각 행마다 `version` 컬럼으로 버전 관리
   - UPDATE 시 `WHERE item_id = ? AND version = ?` 조건 추가
   - `rowcount = 0`이면 충돌 발생 → "다른 사용자가 먼저 수정했습니다" 표시

### 락 획득/해제 (item_locks)

```python
def acquire_item_lock(
    item_id: int,
    locked_by: str,  # 세션 ID 또는 사용자 ID
    lock_duration_minutes: int = 30
) -> bool:
    """
    행 편집 락 획득 (item_id 기준)
    
    Returns:
        True: 락 획득 성공
        False: 이미 다른 사용자가 락 보유 중
    """
    from datetime import datetime, timedelta
    
    expires_at = datetime.now() + timedelta(minutes=lock_duration_minutes)
    
    try:
        cursor.execute("""
            INSERT INTO item_locks (item_id, locked_by, expires_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (item_id) DO UPDATE
            SET locked_by = EXCLUDED.locked_by,
                locked_at = CURRENT_TIMESTAMP,
                expires_at = EXCLUDED.expires_at
            WHERE item_locks.expires_at < CURRENT_TIMESTAMP  -- 만료된 락만 덮어쓰기
        """, (item_id, locked_by, expires_at))
        
        return cursor.rowcount > 0
    except Exception:
        return False  # 락 획득 실패

def release_item_lock(item_id: int, locked_by: str) -> bool:
    """
    행 편집 락 해제
    """
    cursor.execute("""
        DELETE FROM item_locks
        WHERE item_id = %s
          AND locked_by = %s
    """, (item_id, locked_by))
    
    return cursor.rowcount > 0

def cleanup_expired_locks() -> int:
    """
    만료된 락 정리 (주기적으로 실행)
    """
    cursor.execute("""
        DELETE FROM item_locks
        WHERE expires_at < CURRENT_TIMESTAMP
    """)
    return cursor.rowcount
```

### 락 상태 확인 (LEFT JOIN)

```sql
-- 페이지의 모든 행과 락 상태를 함께 조회
SELECT 
    i.item_id,
    i.customer,
    i.product_name,
    i.item_data,
    i.version,
    l.locked_by,
    l.locked_at,
    l.expires_at,
    CASE 
        WHEN l.item_id IS NOT NULL AND l.expires_at > CURRENT_TIMESTAMP 
        THEN true 
        ELSE false 
    END as is_locked
FROM items i
LEFT JOIN item_locks l ON i.item_id = l.item_id
WHERE i.pdf_filename = 'document.pdf'
  AND i.page_number = 1
ORDER BY i.item_order;
```

```python
# Python에서 사용
def get_items_with_lock_status(
    pdf_filename: str,
    page_number: int,
    current_session_id: str
) -> List[dict]:
    """
    페이지의 모든 행과 락 상태를 함께 조회
    """
    cursor.execute("""
        SELECT 
            i.item_id,
            i.customer,
            i.product_name,
            i.item_data,
            i.version,
            i.first_review_checked,
            i.second_review_checked,
            l.locked_by,
            l.expires_at,
            CASE 
                WHEN l.item_id IS NOT NULL 
                     AND l.expires_at > CURRENT_TIMESTAMP 
                     AND l.locked_by != %s
                THEN true 
                ELSE false 
            END as is_locked_by_others
        FROM items i
        LEFT JOIN item_locks l ON i.item_id = l.item_id
        WHERE i.pdf_filename = %s
          AND i.page_number = %s
        ORDER BY i.item_order
    """, (current_session_id, pdf_filename, page_number))
    
    return cursor.fetchall()

# UI에서 사용
items = get_items_with_lock_status("document.pdf", 1, session_id)

for item in items:
    if item['is_locked_by_others']:
        # 다른 사용자가 편집 중
        show_locked_indicator(item['item_id'], item['locked_by'])
    elif item['locked_by'] == session_id:
        # 내가 편집 중
        show_editing_indicator(item['item_id'])
```

### 낙관적 락 (version) 사용 예시

```python
# 1. 행 조회 시 version도 함께 가져오기
def get_item(item_id: int) -> dict:
    """행 조회 (version 포함)"""
    cursor.execute("""
        SELECT item_id, customer, product_name, item_data, version
        FROM items
        WHERE item_id = %s
    """, (item_id,))
    return cursor.fetchone()  # {'item_id': 1, 'version': 3, ...}

# 2. 수정 시 version 체크
def save_item(item_id: int, updates: dict, expected_version: int):
    """행 저장 (낙관적 락 적용)"""
    success, message = update_single_item(
        item_id=item_id,
        updates=updates,
        expected_version=expected_version  # 클라이언트가 읽은 버전
    )
    
    if not success:
        # 충돌 발생
        st.error(f"❌ {message}")
        st.info("💡 페이지를 새로고침하고 다시 시도해주세요.")
        return False
    else:
        st.success("✅ 저장 완료")
        return True

# 3. UI에서 사용
# 페이지 로드 시
item = get_item(item_id=123)
st.session_state[f"item_{item_id}_version"] = item['version']  # 버전 저장

# 저장 시
expected_version = st.session_state.get(f"item_{item_id}_version", 1)
save_item(
    item_id=123,
    updates={"customer": "수정된 거래처"},
    expected_version=expected_version
)
```

### 충돌 시나리오

```
시간 | 사용자 A                    | 사용자 B                    | DB 상태
-----|----------------------------|----------------------------|----------
T1   | item_id=123 조회 (version=1) |                            | version=1
T2   |                            | item_id=123 조회 (version=1) | version=1
T3   | 수정 저장                   |                            | version=2 (A가 수정)
T4   |                            | 수정 저장 시도              | 
T5   |                            | WHERE version=1 → rowcount=0 | version=2 (유지)
T6   |                            | ❌ 충돌 감지!               | 
```

**결과**: 사용자 B는 "다른 사용자가 먼저 수정했습니다" 메시지를 받고, 페이지를 새로고침하여 최신 버전을 다시 읽어야 함

---

## 검색 방법

### 1. 공통 필드 검색 (일반 인덱스 활용)

```sql
-- 거래처명으로 검색 (빠름!)
SELECT * FROM items
WHERE customer ILIKE '%ローソン%'
ORDER BY pdf_filename, page_number, item_order;
```

### 2. 양식지별 필드 검색 (GIN 인덱스 활용)

```sql
-- 請求伝票番号로 검색 (양식지 01)
SELECT * FROM items
WHERE item_data->>'請求伝票番号' = '7690664';

-- 期間開始로 검색
SELECT * FROM items
WHERE item_data->>'期間開始' = '01/01';
```

### 3. 복합 검색

```sql
-- 공통 필드 + JSONB 필드 조합 (복잡한 필터링)
-- 예: 거래처명으로 1차 검색 후 タイプ로 필터링
SELECT * FROM items
WHERE customer ILIKE '%ローソン%'  -- 공통 필드 (B-tree 인덱스 활용)
  AND item_data->>'タイプ' = '販促_通常'  -- 양식지별 필드 (GIN 인덱스 활용)
  AND first_review_checked = true;  -- 검토 상태 (B-tree 인덱스 활용, 빠름!)

-- 다른 예시
SELECT * FROM items
WHERE customer = 'ローソントウカイ'
  AND item_data->>'請求伝票番号' = '7690664'
  AND product_name ILIKE '%チャパゲティ%'
  AND second_review_checked = false;  -- 2차 미검토 항목만
```

---

## 페이지 데이터 조회

### page_data + items 병합

```python
def get_page_result(pdf_filename: str, page_num: int) -> dict:
    """
    페이지 전체 데이터 조회 (page_data + items 병합)
    """
    # 1. page_data 조회 (메타데이터)
    page_data = db.get_page_data(pdf_filename, page_num)
    
    # 2. items 조회 (행 단위 데이터)
    items = db.get_items(pdf_filename, page_num)
    
    # 3. 병합
    result = {
        "page_role": page_data.get("page_role"),
        "page_meta": page_data.get("page_meta", {}),
        "items": []
    }
    
    for item in items:
        # 공통 필드 + JSONB 필드 병합
        merged_item = {
            **{k: v for k, v in item.items() 
               if k in ["customer", "product_name"]},  # 공통 필드만
            **item.get("item_data", {}),  # 양식지별 필드 (amount, quantity, customer_code 등 포함)
            # 검토 상태는 컬럼에서 가져와서 review_status 형태로 변환
            "review_status": {
                "first_review": {
                    "checked": item.get("first_review_checked", False),
                    "reviewed_at": item.get("first_reviewed_at")
                },
                "second_review": {
                    "checked": item.get("second_review_checked", False),
                    "reviewed_at": item.get("second_reviewed_at")
                }
            }
        }
        result["items"].append(merged_item)
    
    return result
```

---

## 마이그레이션 계획

### 1. 스키마 생성

```sql
-- items 테이블 생성
CREATE TABLE items (...);

-- item_locks 테이블 생성 (행 단위 편집 락)
CREATE TABLE item_locks (
    item_id INTEGER PRIMARY KEY REFERENCES items(item_id) ON DELETE CASCADE,
    locked_by VARCHAR(100) NOT NULL,
    locked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL
);

-- 인덱스 생성
CREATE INDEX idx_items_pdf_page ON items(pdf_filename, page_number);
CREATE INDEX idx_items_customer ON items(customer);
CREATE INDEX idx_items_product ON items(product_name);
CREATE INDEX idx_item_locks_expires_at ON item_locks(expires_at);
CREATE INDEX idx_item_locks_locked_by ON item_locks(locked_by);

-- page_data 구조 변경 (items 제거)
ALTER TABLE page_data 
DROP COLUMN IF EXISTS page_json,
ADD COLUMN page_role VARCHAR(50),
ADD COLUMN page_meta JSONB;
```

### 2. 데이터 마이그레이션

```python
# page_data.page_json에서 items 추출하여 items 테이블로 이동
def migrate_data():
    # 1. page_data에서 모든 페이지 조회
    pages = db.get_all_pages()
    
    for page in pages:
        page_json = page['page_json']
        items = page_json.get('items', [])
        
        # 2. 각 item을 items 테이블에 저장
        for idx, item in enumerate(items, 1):
            # 공통 필드와 양식지별 필드 분리
            separated = separate_fields(item, page['form_type'])
            
            db.insert_item(
                pdf_filename=page['pdf_filename'],
                page_number=page['page_number'],
                item_order=idx,
                **separated
            )
        
        # 3. page_data 업데이트 (items 제거)
        page_meta = {k: v for k, v in page_json.items() if k != 'items'}
        db.update_page_meta(
            pdf_filename=page['pdf_filename'],
            page_number=page['page_number'],
            page_role=page_json.get('page_role'),
            page_meta=page_meta
        )
```

---

## 코드 변경 사항

### 1. DB 매니저 메서드 추가

```python
# database/db_manager.py

def insert_item(...) -> int:
    """새 행 추가"""
    
def update_item(item_id: int, updates: dict, expected_version: int) -> tuple[bool, str]:
    """개별 행 수정 (낙관적 락 적용, 충돌 감지)"""
    
def get_items(pdf_filename: str, page_num: int) -> List[dict]:
    """페이지의 모든 행 조회"""
    
def get_item_by_id(item_id: int) -> dict:
    """특정 행 조회 (version 포함, 낙관적 락용)"""
    
def get_items_with_lock_status(pdf_filename: str, page_num: int, session_id: str) -> List[dict]:
    """페이지의 모든 행과 락 상태를 함께 조회 (LEFT JOIN)"""
    
def delete_item(item_id: int) -> bool:
    """행 삭제"""
    
# item_locks 관련 메서드
def acquire_item_lock(item_id: int, locked_by: str, lock_duration_minutes: int = 30) -> bool:
    """행 편집 락 획득 (item_id 기준)"""
    
def release_item_lock(item_id: int, locked_by: str) -> bool:
    """행 편집 락 해제"""
    
def cleanup_expired_locks() -> int:
    """만료된 락 정리 (주기적으로 실행)"""
```

### 2. UI 수정

```python
# modules/ui/aggrid_utils.py
# - items를 조회할 때 공통 필드 + item_data 병합
# - 저장 시 공통 필드와 item_data 분리하여 저장
# - version을 session_state에 저장하여 낙관적 락 적용

# modules/ui/review_components.py
# - 동일하게 수정
# - 저장 시 expected_version 전달하여 충돌 감지
```

### 3. 저장 로직

```python
# 체크박스 변경 시 (일반 컬럼 사용, 빠름!)
def save_review_status(item_id: int, first_checked: bool, second_checked: bool, expected_version: int):
    from datetime import datetime
    
    success, message = db.update_item(
        item_id=item_id,
        updates={
            "first_review_checked": first_checked,
            "second_review_checked": second_checked,
            "first_reviewed_at": datetime.now() if first_checked else None,
            "second_reviewed_at": datetime.now() if second_checked else None,
        },
        expected_version=expected_version  # 낙관적 락
    )
    
    if not success:
        st.error(f"❌ {message}")  # "다른 사용자가 먼저 수정했습니다"
        return False
    return True
```

---

## 장점 요약

1. ✅ **개별 행 수정**: `UPDATE items WHERE item_id = ?`로 간단
2. ✅ **이중 락 메커니즘**: item_locks(UI 제어) + version(낙관적 락, 저장 시 충돌 방지 필수)
3. ✅ **낙관적 락**: version 컬럼으로 저장 시점 충돌 감지 → "다른 사용자가 먼저 수정했습니다" 표시
4. ✅ **검색 성능**: 공통 필드는 일반 인덱스, 양식지별 필드는 GIN 인덱스
5. ✅ **검토 상태 최적화**: JSONB 대신 일반 컬럼 사용 → 검색/필터 압도적으로 빠름, UPDATE 시 전체 JSON 재작성 불필요
6. ✅ **유연한 행 순서 관리**: UNIQUE 제약조건 없어서 삽입/삭제/reorder 자유롭게 처리 가능, 논리적 식별은 item_id만 사용
7. ✅ **유연성**: 양식지 추가 시 스키마 변경 불필요 (JSONB 활용)
8. ✅ **데이터 일관성**: 공통 필드는 컬럼으로 통일, 양식지별 필드는 원본 유지
9. ✅ **설계 원칙 준수**: JSONB는 가변 구조에만 사용, 고정 구조는 일반 컬럼 사용

---

## 단점 및 해결책

### 1. 데이터 중복 가능성
- **문제**: 공통 필드가 컬럼과 item_data에 중복될 수 있음
- **해결**: 저장 로직에서 공통 필드는 컬럼에만 저장, item_data에는 제외

### 2. 조회 시 병합 필요
- **문제**: page_data + items를 합쳐야 페이지 전체 데이터 구성
- **해결**: `get_page_result()` 헬퍼 함수로 자동 병합

### 3. 저장 로직 복잡도
- **문제**: 공통 필드와 JSONB 필드 분리 필요
- **해결**: `separate_fields()` 헬퍼 함수로 자동 분리

---

## 다음 단계

1. ✅ 스키마 생성 스크립트 작성
2. ✅ 마이그레이션 스크립트 작성
3. ✅ DB 매니저 메서드 구현
4. ✅ UI 코드 수정 (AgGrid, 저장 로직)
5. ✅ 테스트
