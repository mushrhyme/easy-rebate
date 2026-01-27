# React 프론트엔드

조건청구서 업로드 및 관리 시스템의 React 프론트엔드입니다.

## 기술 스택

- **React 18** + **TypeScript**
- **Vite** - 빌드 도구
- **Zustand** - 상태 관리
- **React Query** - 서버 상태 관리
- **react-data-grid** - 데이터 그리드
- **Axios** - HTTP 클라이언트

## 설치

```bash
cd frontend
npm install
```

## 개발 서버 실행

```bash
npm run dev
```

브라우저에서 `http://localhost:3000` 접속

## 빌드

```bash
npm run build
```

## 프로젝트 구조

```
frontend/
├── src/
│   ├── components/
│   │   ├── Upload/
│   │   │   └── FormUploadSection.tsx    # 양식지별 업로드 섹션
│   │   ├── Search/
│   │   │   └── CustomerSearch.tsx      # 거래처 검색
│   │   └── Grid/
│   │       └── ItemsGridRdg.tsx        # react-data-grid 아이템 테이블
│   ├── hooks/
│   │   ├── useItems.ts                 # 아이템 관련 훅
│   │   ├── useItemLocks.ts             # 아이템 락 훅
│   │   └── useWebSocket.ts             # WebSocket 훅
│   ├── stores/
│   │   └── uploadStore.ts              # Zustand 업로드 스토어
│   ├── api/
│   │   └── client.ts                   # API 클라이언트
│   ├── types/
│   │   └── index.ts                    # TypeScript 타입 정의
│   ├── config/
│   │   └── formConfig.ts               # 양식지 설정
│   ├── App.tsx                         # 메인 App 컴포넌트
│   └── main.tsx                        # 진입점
└── package.json
```

## 주요 기능

### 1. 파일 업로드
- 양식지별(01~05) PDF 파일 업로드
- 다중 파일 업로드 지원
- WebSocket을 통한 실시간 처리 진행률 표시

### 2. 거래처 검색
- 거래처명으로 검색 (부분 일치/완전 일치)
- 양식지별 필터링
- 검색 결과 페이지별 표시

### 3. 아이템 편집
- react-data-grid를 사용한 테이블 편집
- 낙관적 락을 통한 동시 편집 방지
- 검토 상태 체크박스

## 환경 변수

`.env` 파일 생성 (선택사항):

```env
VITE_API_BASE_URL=http://localhost:8000
```

## 백엔드 연결

프론트엔드는 `vite.config.ts`에서 프록시 설정을 통해 백엔드 API에 연결합니다:

- API: `http://localhost:8000/api/*`
- WebSocket: `ws://localhost:8000/ws/*`

백엔드 서버가 실행 중이어야 합니다.

## 개발 팁

1. **타입 안정성**: 모든 API 응답은 TypeScript 타입으로 정의되어 있습니다.
2. **상태 관리**: 
   - 서버 상태: React Query
   - 클라이언트 상태: Zustand
3. **에러 처리**: React Query의 에러 핸들링을 활용합니다.
