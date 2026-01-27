# react_rebate

조건 요청서 업로드·처리 시스템 (FastAPI + React)

## 다른 곳에서 clone 후

```bash
# 1. 의존성
pip install -r requirements.txt
cd frontend && npm install && cd ..

# 2. .env (프로젝트 루트)
cp .env.example .env
# DB_PASSWORD, OPENAI_API_KEY 등 수정

# 3. PostgreSQL
createdb rebate_db
psql -U postgres -d rebate_db -f database/init_database.sql
psql -U postgres -d rebate_db -f database/restore_users.sql   # admin 사용자

# 4. 실행
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000   # 터미널 1
cd frontend && npm run dev                                     # 터미널 2
```

- API: http://localhost:8000  
- 프론트: http://localhost:3000 (Vite 프록시 → 백엔드)

## 실행만 할 때

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

cd frontend && npm install && npm run dev
```

PostgreSQL 및 `.env` 설정이 선행되어 있어야 합니다.
