# 성능 진단 가이드

## 성능 진단 API 사용법

브라우저 콘솔 또는 터미널에서 다음 명령어로 성능을 진단할 수 있습니다:

```bash
# 성능 진단 API 호출
curl http://172.17.173.27:8000/api/performance/diagnose | jq
```

또는 브라우저에서:
```
http://172.17.173.27:8000/api/performance/diagnose
```

## 주요 병목 지점

### 1. 검토 통계 조회 (get_review_stats)
- **위치**: `backend/api/routes/items.py`
- **문제**: 전체 items 테이블을 GROUP BY로 집계
- **최적화**: 
  - ✅ 인덱스 활용 (`idx_items_pdf_page`)
  - ✅ 프론트엔드 갱신 간격 5초 → 10초로 변경
  - ⚠️ 데이터가 매우 많으면 여전히 느릴 수 있음

### 2. 문서 목록 조회 (get_documents)
- **위치**: `backend/api/routes/documents.py`
- **문제**: 각 문서마다 개별 쿼리로 請求年月 추출 (N+1 쿼리)
- **최적화**: 
  - ✅ 배치 쿼리로 변경 (모든 문서의 첫 페이지 page_meta를 한 번에 조회)
  - 예상 성능 향상: 10-50배

### 3. 페이지 데이터 조회 (get_page_result)
- **위치**: `database/db_manager.py`
- **문제**: form_type과 키 순서를 중복 조회
- **최적화**: 
  - ✅ 한 번만 조회하고 결과 재사용
  - 예상 성능 향상: 2-3배

### 4. Items 조회 (get_items)
- **위치**: `database/db_manager.py`
- **문제**: 각 item마다 JSON 파싱 및 병합 작업
- **최적화**:
  - ✅ form_type과 키 순서를 파라미터로 받아 중복 조회 방지
  - ⚠️ item 수가 많으면 여전히 느릴 수 있음

## 추가 최적화 방안

### 1. 인덱스 확인
다음 SQL로 인덱스가 제대로 생성되었는지 확인:

```sql
SELECT 
    schemaname,
    tablename,
    indexname,
    idx_scan as index_scans
FROM pg_stat_user_indexes
WHERE tablename IN ('documents', 'items', 'page_data')
ORDER BY tablename, indexname;
```

### 2. 쿼리 실행 계획 확인
느린 쿼리의 실행 계획을 확인:

```sql
EXPLAIN ANALYZE
SELECT 
    pdf_filename,
    page_number,
    BOOL_AND(COALESCE(first_review_checked, false)) as first_reviewed,
    COUNT(*) as total_count
FROM items
GROUP BY pdf_filename, page_number;
```

### 3. 캐싱 추가
자주 조회되는 데이터에 캐싱 추가:
- 검토 통계: Redis 또는 메모리 캐시
- 문서 목록: 짧은 TTL 캐시

### 4. 페이지네이션
대량 데이터 조회 시 페이지네이션 적용:
- 검토 통계: 페이지별로 나누어 조회
- 문서 목록: 페이지네이션 추가

## 성능 모니터링

백엔드 로그에서 다음 패턴을 확인:
- `🔍 [get_items]` - items 조회 시간
- `🔍 [get_page_result]` - 페이지 조회 시간
- `🔍 [search_items_by_customer]` - 검색 시간

각 로그에 시간 정보가 포함되어 있으므로, 느린 쿼리를 식별할 수 있습니다.
