# Streamlit → React 전환 가이드

## 개요

조건청구서 업로드 및 관리 시스템을 Streamlit에서 React + FastAPI로 전환했습니다.

## 아키텍처

### 백엔드 (FastAPI)
- **위치**: `backend/`
- **기술**: FastAPI, PostgreSQL, WebSocket
- **포트**: 8000

### 프론트엔드 (React)
- **위치**: `frontend/`
- **기술**: React 18, TypeScript, Vite, Zustand, React Query, AG Grid
- **포트**: 3000

## 시작하기

### 1. 백엔드 실행

```bash
# 의존성 설치
pip install -r requirements.txt

# 환경 변수 설정 (.env 파일)
DB_HOST=localhost
DB_PORT=5432
DB_NAME=rebate_db
DB_USER=postgres
DB_PASSWORD=your_password

# 서버 실행
python -m backend.main
# 또는
./backend/run.sh
```

백엔드 API 문서: `http://localhost:8000/docs`

### 2. 프론트엔드 실행

```bash
cd frontend

# 의존성 설치
npm install

# 개발 서버 실행
npm run dev
```

프론트엔드: `http://localhost:3000`

## 주요 변경사항

### 1. 세션 관리
- **이전**: Streamlit의 `st.session_state` 사용
- **현재**: 클라이언트에서 세션 ID 생성 및 관리 (UUID)

### 2. 파일 업로드
- **이전**: `st.file_uploader` 사용
- **현재**: HTML `<input type="file">` + FormData

### 3. 상태 관리
- **이전**: `st.session_state`로 전역 상태 관리
- **현재**: 
  - 서버 상태: React Query
  - 클라이언트 상태: Zustand

### 4. 실시간 통신
- **이전**: Streamlit의 자동 새로고침
- **현재**: WebSocket을 통한 실시간 진행률 전송

### 5. 데이터 그리드
- **이전**: `st_aggrid` (Streamlit용)
- **현재**: `ag-grid-react` (React용)

## 기존 모듈 재사용

다음 모듈들은 그대로 재사용됩니다:

- ✅ `PdfProcessor` - PDF 처리 로직
- ✅ `DatabaseManager` - 데이터베이스 관리
- ✅ `RAGManager` - RAG 벡터 검색
- ✅ 기타 유틸리티 모듈들

## API 엔드포인트

### 문서 관리
- `POST /api/documents/upload` - 파일 업로드
- `GET /api/documents` - 문서 목록
- `GET /api/documents/{pdf_filename}` - 문서 조회
- `DELETE /api/documents/{pdf_filename}` - 문서 삭제

### 아이템 관리
- `GET /api/items/{pdf_filename}/pages/{page_number}` - 아이템 목록
- `PUT /api/items/{item_id}` - 아이템 업데이트
- `POST /api/items/{item_id}/lock` - 락 획득
- `DELETE /api/items/{item_id}/lock` - 락 해제

### 검색
- `GET /api/search/customer` - 거래처명 검색
- `GET /api/search/{pdf_filename}/pages/{page_number}/image` - 페이지 이미지

### WebSocket
- `WS /ws/processing/{task_id}` - 처리 진행률

자세한 내용은 `backend/API_EXAMPLES.md` 참고

## 개발 팁

### 백엔드
- FastAPI 자동 리로드: `--reload` 옵션 사용
- API 문서: Swagger UI (`/docs`) 또는 ReDoc (`/redoc`)

### 프론트엔드
- Hot Module Replacement (HMR) 지원
- TypeScript 타입 체크 활성화
- React Query DevTools 사용 가능

## 배포

### 백엔드
```bash
# 프로덕션 모드
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### 프론트엔드
```bash
# 빌드
npm run build

# 빌드 결과물: frontend/dist/
```

## 문제 해결

### CORS 오류
백엔드 `backend/core/config.py`에서 `CORS_ORIGINS`에 프론트엔드 URL 추가

### WebSocket 연결 실패
- 백엔드 서버가 실행 중인지 확인
- 프록시 설정 확인 (`vite.config.ts`)

### 타입 오류
```bash
cd frontend
npm run build  # 타입 체크
```

## 다음 단계

1. ✅ 백엔드 API 구축 완료
2. ✅ 프론트엔드 기본 UI 완료
3. 🔄 추가 기능 개발
   - 문서 목록 표시
   - 페이지 네비게이션
   - 고급 검색 기능
   - 사용자 인증 (필요시)
