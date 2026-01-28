# React Rebate - 조건청구서 업로드·처리 시스템

조건청구서 PDF 파일을 업로드하고 AI를 활용하여 자동으로 파싱·관리하는 웹 애플리케이션입니다.

## 📋 목차

- [기술 스택](#기술-스택)
- [주요 기능](#주요-기능)
- [프로젝트 구조](#프로젝트-구조)
- [시작하기](#시작하기)
- [환경 설정](#환경-설정)
- [실행 방법](#실행-방법)
- [API 문서](#api-문서)
- [추가 문서](#추가-문서)
- [문제 해결](#문제-해결)

## 🛠 기술 스택

### 백엔드
- **FastAPI** - Python 웹 프레임워크
- **PostgreSQL** - 관계형 데이터베이스
- **WebSocket** - 실시간 통신
- **RAG (Retrieval-Augmented Generation)** - AI 기반 문서 파싱
- **FAISS** - 벡터 검색

### 프론트엔드
- **React 18** + **TypeScript**
- **Vite** - 빌드 도구
- **Zustand** - 상태 관리
- **React Query** - 서버 상태 관리
- **react-data-grid** - 데이터 그리드

## ✨ 주요 기능

1. **PDF 업로드 및 처리**
   - 양식지별(01~05) PDF 파일 업로드
   - 다중 파일 업로드 지원
   - WebSocket을 통한 실시간 처리 진행률 표시
   - AI 기반 자동 파싱 (Gemini, OpenAI, Upstage)

2. **문서 관리**
   - 문서 목록 조회 및 검색
   - 페이지별 데이터 조회
   - 문서 삭제

3. **데이터 편집**
   - 행 단위 데이터 편집
   - 낙관적 락을 통한 동시 편집 충돌 방지
   - 검토 상태 관리 (1차/2차 검토)

4. **검색 기능**
   - 거래처명으로 검색 (부분 일치/완전 일치)
   - 양식지별 필터링
   - 검색 결과 페이지별 표시

5. **SAP 업로드**
   - 파싱된 데이터를 SAP 양식에 맞게 엑셀 파일 생성

## 📁 프로젝트 구조

```
react_rebate/
├── backend/                 # FastAPI 백엔드
│   ├── api/
│   │   └── routes/          # API 라우트
│   │       ├── documents.py # 문서 관리
│   │       ├── items.py     # 아이템 CRUD
│   │       ├── search.py    # 검색
│   │       └── websocket.py # WebSocket
│   ├── core/                # 핵심 모듈
│   │   ├── config.py        # 설정
│   │   ├── scheduler.py     # 스케줄러
│   │   └── session.py       # 세션 관리
│   └── main.py              # FastAPI 앱 진입점
│
├── frontend/                # React 프론트엔드
│   ├── src/
│   │   ├── components/      # React 컴포넌트
│   │   ├── hooks/           # 커스텀 훅
│   │   ├── stores/          # Zustand 스토어
│   │   ├── api/             # API 클라이언트
│   │   └── types/           # TypeScript 타입
│   └── package.json
│
├── modules/                  # 공통 모듈
│   ├── core/                # 핵심 로직
│   │   ├── extractors/      # PDF 파서 (Gemini, Upstage, RAG)
│   │   ├── processor.py     # 문서 처리
│   │   ├── rag_manager.py   # RAG 관리
│   │   └── storage.py       # 저장소 관리
│   └── utils/               # 유틸리티
│
├── database/                # 데이터베이스
│   ├── init_database.sql    # 초기 스키마
│   ├── db_manager.py        # DB 매니저
│   └── migrations/          # 마이그레이션
│
├── prompts/                 # AI 프롬프트
├── static/                  # 정적 파일 (이미지 등)
└── requirements.txt         # Python 의존성
```

## 🚀 시작하기

### 사전 요구사항

- Python 3.9+
- Node.js 18+
- PostgreSQL 12+
- npm 또는 yarn

### 1. 저장소 클론

```bash
git clone <repository-url>
cd react_rebate
```

### 2. 의존성 설치

#### Python 의존성

```bash
pip install -r requirements.txt
```

#### Node.js 의존성

```bash
cd frontend
npm install
cd ..
```

### 3. 데이터베이스 설정

```bash
# PostgreSQL 데이터베이스 생성
createdb rebate_db

# 스키마 초기화
psql -U postgres -d rebate_db -f database/init_database.sql

# 기본 사용자 복원 (선택사항)
psql -U postgres -d rebate_db -f database/restore_users.sql
```

## ⚙️ 환경 설정

프로젝트 루트에 `.env` 파일을 생성하고 다음 변수를 설정하세요:

```env
# 데이터베이스 설정
DB_HOST=localhost
DB_PORT=5432
DB_NAME=rebate_db
DB_USER=postgres
DB_PASSWORD=your_password

# API 서버 설정
API_HOST=0.0.0.0
API_PORT=8000
DEBUG=False

# AI API 키 (필요한 것만 설정)
OPENAI_API_KEY=your_openai_api_key
GEMINI_API_KEY=your_gemini_api_key
UPSTAGE_API_KEY=your_upstage_api_key
AZURE_API_KEY=your_azure_api_key
AZURE_API_ENDPOINT=your_azure_endpoint

# 로컬 IP (WebSocket용)
LOCAL_IP=172.17.173.27
```

## ▶️ 실행 방법

### 개발 모드

#### 1. 백엔드 실행

```bash
# 프로젝트 루트에서
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

또는

```bash
python -m backend.main
```

백엔드 API 문서: http://localhost:8000/docs

#### 2. 프론트엔드 실행

```bash
cd frontend
npm run dev
```

프론트엔드: http://localhost:3000

### 프로덕션 모드

#### 백엔드

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 4
```

#### 프론트엔드

```bash
cd frontend
npm run build
# 빌드 결과물: frontend/dist/
```

## 📚 API 문서

### 주요 엔드포인트

#### 문서 관리
- `POST /api/documents/upload` - PDF 파일 업로드
- `GET /api/documents` - 문서 목록 조회
- `GET /api/documents/{pdf_filename}` - 문서 정보 조회
- `DELETE /api/documents/{pdf_filename}` - 문서 삭제

#### 아이템 관리
- `GET /api/items/{pdf_filename}/pages/{page_number}` - 페이지 아이템 조회
- `PUT /api/items/{item_id}` - 아이템 업데이트
- `POST /api/items/{item_id}/lock` - 아이템 락 획득
- `DELETE /api/items/{item_id}/lock` - 아이템 락 해제

#### 검색
- `GET /api/search/customer` - 거래처명 검색
- `GET /api/search/{pdf_filename}/pages/{page_number}/image` - 페이지 이미지

#### WebSocket
- `WS /ws/processing/{task_id}` - 처리 진행률 실시간 수신

자세한 API 사용 예제는 [`backend/API_EXAMPLES.md`](backend/API_EXAMPLES.md)를 참고하세요.

## 📖 추가 문서

### 백엔드
- [`backend/README.md`](backend/README.md) - 백엔드 상세 문서
- [`backend/API_EXAMPLES.md`](backend/API_EXAMPLES.md) - API 사용 예제

### 프론트엔드
- [`frontend/README.md`](frontend/README.md) - 프론트엔드 상세 문서

### 데이터베이스
- [`database/SCHEMA.md`](database/SCHEMA.md) - 데이터베이스 스키마 문서
- [`database/ITEMS_TABLE_DESIGN.md`](database/ITEMS_TABLE_DESIGN.md) - Items 테이블 설계 문서
- [`database/PERFORMANCE_ANALYSIS.md`](database/PERFORMANCE_ANALYSIS.md) - 성능 분석 및 개선 방안

### 기능 문서
- [`sap_upload.md`](sap_upload.md) - SAP 업로드 엑셀 양식 가이드
- [`PERFORMANCE_DIAGNOSIS.md`](PERFORMANCE_DIAGNOSIS.md) - 성능 진단 가이드

## 🔧 문제 해결

### CORS 오류
백엔드 `backend/core/config.py`에서 `CORS_ORIGINS`에 프론트엔드 URL을 추가하세요.

### WebSocket 연결 실패
- 백엔드 서버가 실행 중인지 확인
- 프론트엔드 `vite.config.ts`의 프록시 설정 확인

### 데이터베이스 연결 오류
- PostgreSQL 서버가 실행 중인지 확인
- `.env` 파일의 DB 설정이 올바른지 확인

### 타입 오류 (프론트엔드)
```bash
cd frontend
npm run build  # 타입 체크
```

### 성능 문제
- [`PERFORMANCE_DIAGNOSIS.md`](PERFORMANCE_DIAGNOSIS.md) 참고
- [`database/PERFORMANCE_ANALYSIS.md`](database/PERFORMANCE_ANALYSIS.md) 참고

## 📝 라이선스

이 프로젝트는 내부 사용을 위한 것입니다.

## 👥 기여

프로젝트 개선 제안이나 버그 리포트는 이슈로 등록해주세요.
