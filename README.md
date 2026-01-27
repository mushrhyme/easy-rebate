# react_rebate

조건 요청서 업로드·처리 시스템 (FastAPI + React)

## 실행

```bash
# Python 의존성
pip install -r requirements.txt

# 백엔드 (프로젝트 루트에서)
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# 프론트엔드
cd frontend && npm install && npm run dev
```

PostgreSQL 및 `.env` 설정이 필요합니다.
