# 프로젝트 개선 사항 (시급도 순)

## 🔴 시급한 문제 (즉시 수정 필요)

### 1. 보안: .env 파일에 API 키 노출
**위험도**: 🔴 매우 높음  
**위치**: `.env` 파일  
**문제**: 실제 API 키가 소스코드에 포함되어 있음 (gitignore에 있지만 파일 자체에 노출)

```env
GEMINI_API_KEY=your-gemini-api-key-here
OPENAI_API_KEY=your-openai-api-key-here
UPSTAGE_API_KEY=your-upstage-api-key-here
AZURE_API_KEY=your-azure-api-key-here
```

**조치**:
- 즉시 모든 API 키를 무효화하고 새로 발급받기
- `.env.example` 파일 생성 (값 없이 키 이름만)
- `.env` 파일을 절대 커밋하지 않도록 확인
- Git 히스토리에서 API 키 제거 (필요시 `git-filter-repo` 사용)

### 2. SQL Injection 위험
**위험도**: 🔴 높음  
**위치**: `database/db_manager.py`, `database/db_items.py` 등  
**문제**: f-string으로 SQL 쿼리를 동적 구성하는 부분이 있음

**예시**:
```python
# database/db_manager.py:94
cursor.execute(f"""
    SELECT *
    FROM {table_name}
    WHERE pdf_filename = %s
""", (pdf_filename,))
```

**조치**:
- `table_name`은 `table_selector.get_table_name()`을 통해 검증된 값이지만, 더 안전하게 처리
- 모든 동적 테이블명은 화이트리스트 검증 추가
- SQL 쿼리 빌더 라이브러리 고려 (SQLAlchemy Core 등)

### 3. 데이터베이스 연결 풀 정리 누락
**위험도**: 🟡 중간  
**위치**: `database/db_manager.py`, `database/registry.py`  
**문제**: `DatabaseManager`에 `close()` 메서드가 없는데 `registry.py`에서 호출함

```python
# registry.py:30
_APP_DB.close()  # 하지만 db_manager.py에 close() 메서드가 없음
```

**조치**:
- `DatabaseManager`에 `close()` 메서드 추가하여 연결 풀 정리
- FastAPI lifespan에서 종료 시 호출하도록 수정

### 4. 전역 예외 핸들러가 너무 단순함
**위험도**: 🟡 중간  
**위치**: `backend/main.py:138-144`  
**문제**: 모든 예외를 500으로 처리하고 상세 정보를 노출

```python
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)}  # 상세 에러 정보 노출
    )
```

**조치**:
- 예외 타입별로 적절한 HTTP 상태 코드 반환
- 프로덕션 환경에서는 상세 에러 메시지 숨기기
- 로깅 시스템으로 에러 기록

## 🟡 중요하지만 덜 시급한 문제

### 5. 로깅: print() 문 과다 사용
**위험도**: 🟡 중간  
**위치**: 전체 프로젝트 (608개 print() 문 발견)  
**문제**: 디버깅용 print()가 프로덕션 코드에 남아있음

**조치**:
- Python `logging` 모듈로 전환
- 로그 레벨 설정 (DEBUG, INFO, WARNING, ERROR)
- 프로덕션에서는 INFO 이상만 출력
- 구조화된 로깅 (JSON 형식) 고려

**예시**:
```python
# 현재
print(f"✅ PDF 파싱 완료: {pdf_name}")

# 개선
import logging
logger = logging.getLogger(__name__)
logger.info(f"PDF 파싱 완료: {pdf_name}")
```

### 6. 에러 처리 일관성 부족
**위험도**: 🟡 중간  
**위치**: `backend/api/routes/*.py`  
**문제**: 각 라우트마다 에러 처리 방식이 다름

**조치**:
- 공통 에러 핸들러 함수 생성
- 커스텀 예외 클래스 정의
- 에러 응답 형식 표준화

### 7. 하드코딩된 설정값
**위험도**: 🟢 낮음  
**위치**: `modules/utils/config.py`, `backend/core/config.py`  
**문제**: 일부 설정값이 코드에 하드코딩되어 있음

**예시**:
```python
# modules/utils/config.py:46
dpi: int = 300  # 하드코딩
top_k: int = 15  # 하드코딩
```

**조치**:
- 환경 변수나 설정 파일로 이동
- 기본값은 유지하되 변경 가능하도록

### 8. 코드 중복
**위험도**: 🟢 낮음  
**위치**: 여러 파일  
**문제**: 비슷한 패턴이 여러 곳에서 반복됨

**예시**:
- DB 연결 패턴
- 에러 처리 패턴
- 로깅 패턴

**조치**:
- 공통 유틸리티 함수로 추출
- 데코레이터 패턴 활용

## 📝 개선 제안 (선택사항)

### 9. 타입 힌팅 보완
- 일부 함수에 타입 힌팅이 누락되어 있음
- `mypy`로 타입 체크 추가 고려

### 10. 테스트 코드 추가
- 현재 테스트 코드가 보이지 않음
- 핵심 비즈니스 로직에 대한 단위 테스트 추가

### 11. API 문서화 개선
- FastAPI 자동 문서는 있지만, 추가 설명이 필요한 엔드포인트들에 대한 문서 보완

### 12. 성능 모니터링
- 현재 성능 측정 코드가 있지만, 구조화된 모니터링 시스템 고려
- APM 도구 도입 검토 (예: Sentry, DataDog)

---

## 우선순위 요약

1. **즉시 수정**: 보안 문제 (API 키 노출, SQL Injection)
2. **이번 주 내**: DB 연결 정리, 예외 핸들러 개선
3. **이번 달 내**: 로깅 시스템 전환, 에러 처리 표준화
4. **점진적 개선**: 코드 중복 제거, 타입 힌팅, 테스트 추가
