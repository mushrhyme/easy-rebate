# FastAPI 백엔드

조건청구서 업로드 및 관리 시스템의 FastAPI 백엔드입니다.

## 구조

```
backend/
├── main.py                 # FastAPI 메인 애플리케이션
├── api/
│   ├── routes/
│   │   ├── documents.py    # 문서 업로드/조회 API
│   │   ├── items.py         # 아이템 CRUD API
│   │   ├── search.py        # 검색 API
│   │   └── websocket.py     # WebSocket 실시간 통신
│   └── dependencies.py     # 의존성 주입
└── core/
    ├── config.py           # 설정 관리
    └── session.py          # 세션 관리
```

## 설치

```bash
# 프로젝트 루트에서
pip install -r requirements.txt
```

## 환경 변수 설정

`.env` 파일에 다음 변수를 설정하세요:

```env
# API 서버 설정
API_HOST=0.0.0.0
API_PORT=8000
DEBUG=False

# 데이터베이스 설정
DB_HOST=localhost
DB_PORT=5432
DB_NAME=rebate_db
DB_USER=postgres
DB_PASSWORD=your_password

# OpenAI API (RAG 사용 시)
OPENAI_API_KEY=your_openai_api_key
```

## 실행

### 개발 모드

```bash
# 프로젝트 루트에서
python -m backend.main

# 또는 uvicorn 직접 실행
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### 프로덕션 모드

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 4
```

## API 엔드포인트

### 문서 관리

- `POST /api/documents/upload` - PDF 파일 업로드 및 처리
- `GET /api/documents` - 문서 목록 조회
- `GET /api/documents/{pdf_filename}` - 특정 문서 정보 조회
- `DELETE /api/documents/{pdf_filename}` - 문서 삭제
- `GET /api/documents/{pdf_filename}/pages` - 문서의 페이지 목록 조회

### 아이템 관리

- `GET /api/items/{pdf_filename}/pages/{page_number}` - 페이지의 아이템 목록 조회
- `PUT /api/items/{item_id}` - 아이템 업데이트 (낙관적 락)
- `POST /api/items/{item_id}/lock` - 아이템 락 획득
- `DELETE /api/items/{item_id}/lock` - 아이템 락 해제

### 검색

- `GET /api/search/customer` - 거래처명으로 검색
- `GET /api/search/{pdf_filename}/pages/{page_number}/image` - 페이지 이미지 조회

### WebSocket

- `WS /ws/processing/{task_id}` - PDF 처리 진행률 실시간 수신

## 예제

### 파일 업로드

```bash
curl -X POST "http://localhost:8000/api/documents/upload" \
  -F "form_type=01" \
  -F "files=@example.pdf"
```

### 문서 목록 조회

```bash
curl "http://localhost:8000/api/documents?form_type=01"
```

### WebSocket 연결 (JavaScript)

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/processing/session-id');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Progress:', data);
};
```

## 기존 모듈 재사용

백엔드는 기존 Python 모듈을 최대한 재사용합니다:

- `PdfProcessor` - PDF 처리 로직
- `DatabaseManager` - 데이터베이스 관리
- `RAGManager` - RAG 벡터 검색
- 기타 유틸리티 모듈들

## 주의사항

1. **세션 관리**: FastAPI는 Streamlit의 `st.session_state`를 사용하지 않으므로, 세션 ID를 클라이언트에서 관리해야 합니다.

2. **파일 처리**: 업로드된 파일은 임시 디렉토리에 저장되며, 처리 완료 후 정리됩니다.

3. **WebSocket**: PDF 처리 진행률은 WebSocket을 통해 실시간으로 전송됩니다. 클라이언트는 `task_id`(세션 ID)를 사용하여 연결합니다.ㅇ
