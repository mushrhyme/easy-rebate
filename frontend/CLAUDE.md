# Frontend — React 19 + TypeScript + Vite

## 실행

```bash
npm run dev    # Vite 개발서버 (포트 3002, 0.0.0.0)
npm run build  # 프로덕션 빌드 (tsc && vite build)
npm run lint   # ESLint
```

## 탭 구조 (App.tsx)

1. **Dashboard** — 문서 현황 대시보드
2. **Upload** — PDF 업로드 + WebSocket 실시간 진행률
3. **Search (검색)** — 고객/문서 검색 + 데이터 그리드 편집
4. **Answer Key (解答作成)** — 단일 페이지 정답 편집
5. **SAP Upload** — SAP용 Excel 생성·내보내기
6. **RAG Admin** — 벡터 DB 관리 (관리자 전용)

## 컴포넌트 구조 (`src/components/`)

```
components/
├── Upload/           # 업로드 관련
│   ├── FormUploadSection.tsx    — 드래그앤드롭 업로드 + 양식 선택
│   ├── UploadedFilesList.tsx    — 업로드 완료 파일 목록
│   ├── UploadProgressList.tsx   — WebSocket 실시간 진행률
│   └── UploadPagePreview.tsx    — 페이지 미리보기
├── Search/
│   └── CustomerSearch.tsx       — 고객/문서 검색 + 필터
├── Grid/             # 메인 데이터 그리드 (react-data-grid)
│   ├── ItemsGridRdg.tsx         — 메인 편집 가능 그리드
│   ├── useItemsGridColumns.tsx  — 컬럼 정의 훅
│   ├── ReviewCheckboxCell.tsx   — 1차/2차 검토 체크박스
│   ├── ActionCellWithMenu.tsx   — 행 액션 메뉴
│   ├── AttachmentModal.tsx      — 첨부파일 모달
│   ├── UnitPriceMatchModal.tsx  — 단가 매칭 모달
│   └── ComplexFieldDetail.tsx   — JSON 필드 편집기
├── AnswerKey/        # 정답 편집 탭
│   ├── AnswerKeyTab.tsx         — 탭 메인
│   ├── AnswerKeyLeftPanel.tsx   — 아이템 목록 (좌측)
│   ├── AnswerKeyRightPanel.tsx  — 아이템 상세 (우측)
│   └── answerKeySaveUtils.ts    — 저장 유틸
├── SAPUpload/
│   └── SAPUpload.tsx            — SAP Excel 내보내기
├── Auth/
│   ├── Login.tsx                — 로그인 화면
│   └── ChangePasswordModal.tsx  — 비밀번호 변경
├── Admin/
│   └── RagAdminPanel.tsx        — RAG 관리자 패널
├── Dashboard/
│   └── Dashboard.tsx            — 대시보드
└── ErrorBoundary.tsx
```

## 상태관리

| 방식 | 용도 | 위치 |
|------|------|------|
| **Zustand** | 업로드 진행 상태, 파일 목록 | `stores/uploadStore.ts` |
| **React Query** | 서버 데이터 캐싱 (문서, 아이템, 검색) | 각 컴포넌트/훅에서 사용 |
| **Context** | 인증 상태, 토스트 알림 | `contexts/AuthContext.tsx`, `ToastContext.tsx` |

## 커스텀 훅 (`src/hooks/`)

- **useItems.ts** — 아이템 CRUD (React Query mutations)
- **useItemLocks.ts** — optimistic locking (락 획득/해제)
- **useWebSocket.ts** — WebSocket 연결 (처리 진행률)
- **useFormTypes.ts** — 양식 타입 목록 조회

## API 클라이언트 (`src/api/`)

- **client.ts** — Axios 인스턴스 (baseURL: `/api`, 인터셉터)

## 설정 (`src/config/`)

- **formConfig.ts** — 업로드 채널 (`finet`/`mail`), 양식 타입은 API에서 동적 로드
- **sapUploadFormulas.ts** — SAP Excel 내보내기 수식/컬럼 매핑

## 타입 정의 (`src/types/index.ts`)

주요 타입: `Document`, `Item`, `ItemUpdateRequest`(version 포함), `SearchResult`,
`WebSocketMessage`(connected|start|progress|complete|error|page_complete),
`FormType`, `UploadChannel`(finet|mail), `SapFormulasConfig`
