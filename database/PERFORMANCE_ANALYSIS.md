# 데이터베이스 성능 분석 및 개선 방안

## 현재 상황
- 데이터가 적은데도 UI에서 이미지나 데이터 조회 시 지연 발생
- 수십만 행 저장 시 성능 문제 우려

## 발견된 성능 문제점

### 1. ⚠️ UNION ALL 사용으로 인한 비효율적 쿼리

**문제 위치**: `get_page_image_path()`, `get_items()` 등
```python
# 현재 방식 (비효율적)
SELECT image_path FROM page_images_current WHERE ...
UNION ALL
SELECT image_path FROM page_images_archive WHERE ...
```

**문제점**:
- 두 테이블을 모두 스캔하여 비효율적
- current에 데이터가 있으면 archive 조회 불필요
- 인덱스 활용이 제한적

**개선 방안**:
```python
# 1. current에서 먼저 조회
# 2. 없으면 archive에서 조회
# 3. 또는 테이블 선택 로직 개선
```

### 2. ⚠️ N+1 쿼리 문제

**문제 위치**: `get_page_results()`
```python
# 현재 방식 (N+1 쿼리)
for page_num in page_numbers:
    page_result = self.get_page_result(pdf_filename, page_num)  # 각 페이지마다 쿼리 실행
```

**문제점**:
- 페이지 수만큼 쿼리가 반복 실행됨
- 수십만 행이면 수백~수천 페이지 → 수백~수천 번의 쿼리

**개선 방안**:
- 배치 조회로 한 번에 모든 페이지 데이터 가져오기
- JOIN을 활용한 단일 쿼리로 변경

### 3. ⚠️ JSONB 파싱 오버헤드

**문제 위치**: `get_items()` 메서드
```python
# 각 행마다 JSONB 파싱
for row in rows:
    item_data = row_dict.get('item_data', {})
    if isinstance(item_data, str):
        item_data = json.loads(item_data)  # 매번 파싱
```

**문제점**:
- 수십만 행이면 수십만 번의 JSON 파싱
- Python 레벨에서 파싱하므로 DB보다 느림

**개선 방안**:
- PostgreSQL의 JSONB 연산자 활용 (DB에서 파싱)
- 필요한 필드만 선택적으로 조회

### 4. ⚠️ 인덱스 활용 부족

**현재 인덱스 상태**:
- ✅ `idx_items_current_pdf_page` - (pdf_filename, page_number)
- ✅ `idx_items_current_pdf_page_order` - (pdf_filename, page_number, item_order)
- ✅ `idx_items_current_data_gin` - GIN 인덱스 (item_data)

**잠재적 문제**:
- `get_items()`에서 `items_current`만 조회하는데, archive도 확인해야 할 수 있음
- 테이블 선택 로직이 명확하지 않음

### 5. ⚠️ 이미지 경로 조회 최적화 부족

**문제 위치**: `get_page_image_path()`
```python
# UNION ALL로 두 테이블 모두 조회
SELECT image_path FROM page_images_current WHERE ...
UNION ALL
SELECT image_path FROM page_images_archive WHERE ...
LIMIT 1
```

**개선 방안**:
- COALESCE를 사용한 단일 쿼리
- 또는 current 먼저, 없으면 archive 조회

## 개선 방안

### 우선순위 1: 쿼리 최적화

1. **UNION ALL → 조건부 조회로 변경**
   ```sql
   -- 개선된 방식
   SELECT COALESCE(
       (SELECT image_path FROM page_images_current 
        WHERE pdf_filename = %s AND page_number = %s LIMIT 1),
       (SELECT image_path FROM page_images_archive 
        WHERE pdf_filename = %s AND page_number = %s LIMIT 1)
   ) as image_path
   ```

2. **배치 조회로 N+1 쿼리 해결**
   ```python
   # 한 번에 모든 페이지 조회
   SELECT page_number, page_role, page_meta
   FROM page_data
   WHERE pdf_filename = %s
   ORDER BY page_number
   ```

### 우선순위 2: 인덱스 확인 및 추가

1. **현재 인덱스 상태 확인**
   ```sql
   -- 인덱스 사용 여부 확인
   EXPLAIN ANALYZE
   SELECT * FROM items_current
   WHERE pdf_filename = 'test.pdf' AND page_number = 1
   ORDER BY item_order;
   ```

2. **필요시 복합 인덱스 추가**
   - 이미 대부분의 인덱스가 설정되어 있음
   - 쿼리 실행 계획 확인 필요

### 우선순위 3: JSONB 처리 최적화

1. **DB 레벨에서 JSONB 필드 선택**
   ```sql
   -- 필요한 필드만 선택
   SELECT 
       item_id,
       customer,
       product_name,
       item_data->>'請求伝票番号' as invoice_number,  -- DB에서 파싱
       item_data->>'金額' as amount
   FROM items_current
   WHERE pdf_filename = %s AND page_number = %s
   ```

2. **Python 레벨 파싱 최소화**
   - JSONB는 이미 파싱된 상태이므로 추가 파싱 불필요
   - `json.loads()` 호출 최소화

### 우선순위 4: 페이지네이션 추가

1. **대량 데이터 조회 시 LIMIT/OFFSET 사용**
   ```python
   def get_items(
       self,
       pdf_filename: str,
       page_number: int,
       limit: int = 1000,  # 기본값 설정
       offset: int = 0
   ):
       # LIMIT/OFFSET 추가
   ```

## 예상 성능 개선 효과

### 현재 (문제 상황)
- 페이지당 조회: ~100-500ms (데이터 적을 때도)
- 수십만 행 조회: 수십 초 ~ 수분 소요 예상

### 개선 후 (예상)
- 페이지당 조회: ~10-50ms (인덱스 활용)
- 수십만 행 조회: 수 초 내 완료 (배치 조회 + 인덱스)

## 다음 단계

1. ✅ 성능 분석 완료
2. ⏳ 쿼리 최적화 구현
3. ⏳ 인덱스 사용 확인
4. ⏳ 성능 테스트
