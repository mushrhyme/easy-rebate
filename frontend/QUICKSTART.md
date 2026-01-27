# 빠른 시작 가이드

## 1. 의존성 설치

```bash
cd frontend
npm install
```

## 2. 개발 서버 실행

```bash
npm run dev
```

브라우저에서 `http://localhost:3000` 접속

## 3. 백엔드 서버 실행 (별도 터미널)

```bash
# 프로젝트 루트에서
python -m backend.main
```

또는

```bash
./backend/run.sh
```

백엔드 API: `http://localhost:8000`

## 문제 해결

### npm install 오류
- Node.js 버전 확인 (v18 이상 권장)
- `npm cache clean --force` 후 재시도

### 포트 충돌
- 프론트엔드 포트 변경: `vite.config.ts`에서 `server.port` 수정
- 백엔드 포트 변경: `.env` 파일에서 `API_PORT` 수정
