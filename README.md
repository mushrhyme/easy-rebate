# React Rebate - 조건청구서 업로드·처리 시스템

조건청구서 PDF 업로드 → 파싱·검토·수정 → SAP 업로드용 엑셀 생성까지 처리하는 풀스택 시스템입니다.

---

### 1. 필요한 것 설치 (최초 1회)

| 항목 | 설치 방법 |
|------|-----------|
| **Git** | [git-scm.com](https://git-scm.com/) 에서 다운로드 후 설치 |
| **Node.js** | [nodejs.org](https://nodejs.org/) LTS 버전 설치 (18 이상 권장) |
| **PostgreSQL** | [postgresql.org](https://www.postgresql.org/download/) 에서 설치 후 DB 서버 실행 |
| **uv** (Python 패키지/환경 관리) | 터미널에서: `curl -LsSf https://astral.sh/uv/install.sh \| sh` |

Python은 **uv가 알아서 맞는 버전을 씁니다.** 별도로 Python을 설치할 필요는 없습니다 (uv 설치 시 함께 준비됨).

---

### 2. 프로젝트 받기

```bash
git clone <저장소 URL> react_rebate
cd react_rebate
```

---

### 3. 백엔드 (Python)

**3.1 의존성 설치 (가상환경 자동 생성)**

```bash
uv sync
```

`pip install` 은 사용하지 않습니다. 이 명령 한 번이면 됩니다.

**3.2 환경 변수 파일 만들기**

프로젝트 루트에 `.env` 파일을 만들고 아래 항목을 채웁니다.  
(기존 PC에서 복사해 오거나, 값만 새로 입력합니다.)

- `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` 등 사용하는 API 키
- `AZURE_API_KEY`, `AZURE_API_ENDPOINT` (Azure 사용 시)
- `UPSTAGE_API_KEY` (Upstage OCR 사용 시)
- PostgreSQL 연결 정보 (백엔드 설정에서 DB URL 쓰는 경우 여기서 읽을 수 있도록)
- `LOCAL_IP`, `DEBUG` 등 (필요 시)

`.env` 예시는 프로젝트에 `.env.example` 이 있다면 참고하고, 없으면 `backend/core/config.py` 에서 어떤 변수를 쓰는지 확인하면 됩니다.

**3.3 DB 생성 및 스키마 적용**

PostgreSQL에 DB를 만들고, 프로젝트 스키마를 넣습니다.

```bash
# 예: DB 생성 (PostgreSQL 접속 후 또는 createdb)
createdb rebate_db

# 스키마 적용
psql -U postgres -d rebate_db -f database/init_database.sql
```

실제 DB 이름·사용자명은 사용 중인 환경에 맞게 바꿉니다.

**3.4 백엔드 서버 실행**

```bash
uv run rebate-server
```

개발 시 자동 리로드가 필요하면 `.env` 에 `DEBUG=true` 를 두거나, 다음처럼 실행합니다.

```bash
DEBUG=true uv run rebate-server
```

---

### 4. 프론트엔드 (React)

**다른 터미널**에서 실행합니다.

**4.1 의존성 설치**

```bash
cd frontend
npm install
```

**4.2 개발 서버 실행**

```bash
npm run dev
```

브라우저에서 표시되는 주소(예: `http://localhost:5173`)로 접속합니다.  
API는 백엔드 주소를 가리키도록 `frontend` 쪽 설정(`.env` 또는 `VITE_*`)을 맞춰 둡니다.

---

### 5. 정리 체크리스트

| 순서 | 할 일 | 명령/비고 |
|------|--------|-----------|
| 1 | Git, Node, PostgreSQL, uv 설치 | 위 표 참고 |
| 2 | 저장소 클론 | `git clone ...` 후 `cd react_rebate` |
| 3 | 백엔드 의존성 | `uv sync` |
| 4 | 환경 변수 | 루트에 `.env` 생성·작성 |
| 5 | DB 생성·스키마 | `createdb` + `psql ... init_database.sql` |
| 6 | 백엔드 실행 | `uv run rebate-server` |
| 7 | 프론트 의존성 | `cd frontend` → `npm install` |
| 8 | 프론트 실행 | `npm run dev` |

가상환경을 수동으로 만들거나 `activate` 할 필요 없습니다. `uv sync` 후 `uv run rebate-server` 만 하면 됩니다.

**운영 서버에서 uv 없이 실행할 때:** 프로젝트 루트에서 `./run.sh` 로 실행할 수 있습니다 (reload 없음).

---

## 참고 문서

- **DB 스키마:** `database/SCHEMA.md`
- **SAP 엑셀·RAG·처리 흐름:** `sap_upload.md` 등
