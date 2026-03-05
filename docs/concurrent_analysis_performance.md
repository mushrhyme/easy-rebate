# 동시 분석 시 성능 차이 원인

## 현상

- **한 탭에서 문서 A 분석 → 끝난 뒤 문서 B 분석**: 정상 체감 성능
- **탭 1에서 문서 A 분석 중, 탭 2에서 문서 B 분석 요청**: 둘 다 느려지거나 LLM 결과가 불안정해지는 느낌

## 원인

두 요청이 **같은 프로세스 안에서 동시에** 돌아가며, **공유 자원**을 같이 쓰기 때문입니다.

### 1. RAG 검색 공유 (가장 유력)

- **전역 싱글톤**: `get_rag_manager()` → 하나의 `RAGManager` 인스턴스만 사용
- **같은 임베딩 모델**: `SentenceTransformer` 한 개. 두 분석이 동시에 `model.encode()` 호출
  - CPU/메모리 경합, PyTorch 내부 동작으로 인해 지연·불안정 가능
- **같은 BM25/FAISS 인덱스**: `_build_bm25_index()`가 동시에 호출되면 race 가능, 검색 시에도 공유 구조체 동시 접근
- **결과**: RAG로 “유사 예제”를 찾는 단계가 두 요청에서 겹치면, 검색 지연·변동이 커지고, 그 다음 LLM 단계에도 영향을 줄 수 있음

### 2. API·리소스 경합

- **OpenAI**: 두 분석이 동시에 페이지 수 × 1회씩 LLM 호출 → RPM/TPM 제한에 걸리거나 지연 증가 가능
- **스레드 풀**: `run_in_executor(None, ...)`로 기본 스레드 풀 사용. 한 분석이 `extract_pages_with_rag` 내부에서 또 스레드 풀(예: 5 워커)을 쓰므로, 동시 두 분석이면 스레드 수가 크게 늘어나 CPU 경합이 커짐

### 3. 정리

| 구분 | 한 번에 한 문서만 분석 | 두 탭에서 동시 분석 |
|------|------------------------|---------------------|
| RAG 검색 | 한 스레드만 임베딩/BM25/FAISS 사용 | 두 스레드가 같은 RAGManager·같은 모델 동시 사용 → 경합 |
| LLM 호출 | 한 문서의 페이지만 동시 호출 | 두 문서의 페이지들이 한꺼번에 API 호출 → rate limit·지연 가능 |
| CPU | 한 작업 부하만 | 두 작업 부하 겹침 |

그래서 **동시에 다른 탭에서 분석할 때**가 상대적으로 느리거나 불안정하게 느껴지는 것이 자연스러운 동작에 가깝습니다.

## 대응 (구현된 것)

- **RAG 검색 직렬화**: `RAGManager`에 `_search_lock`을 두고, `search_similar_advanced()` 진입 시 이 락을 잡도록 함.
  - 효과: 서로 다른 탭의 분석이라도 **RAG 검색(임베딩 + BM25 + FAISS)은 한 번에 하나만** 실행됨.
  - 한쪽이 검색하는 동안 다른 쪽은 검색만 잠시 대기하고, LLM 호출은 각자 스레드 풀에서 그대로 병렬로 수행됨.
- 기대: 동시 분석 시에도 RAG 단계에서의 경합이 줄어들어, **체감 성능과 안정성이 나아질 수 있음**. (완전히 “한 문서씩만” 할 때와 동일해지지는 않음.)

## DB·이벤트 루프 대응 (구현된 것)

- **이벤트 루프 블로킹 완화**: `DatabaseManager.run_sync()`로 동기 DB 작업을 스레드 풀에서 실행. async 라우트에서 `with db.get_connection()` 대신 `await db.run_sync(sync_fn, ...)` 사용.
- **generate_page_images**: PDF→이미지 생성·파일 저장·DB INSERT를 `_generate_all_page_images_sync`로 묶고 `asyncio.to_thread()`로 실행해, 해당 API 호출 중에도 이벤트 루프가 블로킹되지 않도록 함.
- **인증 의존성**: `get_current_user` / `get_current_user_optional` 등은 async로 변경하고 `db.get_session_user`를 `run_sync`로 호출.
- **동시 PDF 분석 제한**: 사용자별 세마포어(1인당 동시 1건, `MAX_CONCURRENT_ANALYSES_PER_USER`) + 전역 상한(기본 20, `MAX_CONCURRENT_ANALYSES`). 10명이 동시 업로드해도 각자 1건씩 병렬 처리되고, 한 사용자가 다수 업로드 시에는 해당 사용자만 순차 대기.
- **DB 연결 풀**: `acquire_item_lock` 등에서 연결 블록을 하나로 합쳐 풀 점유 시간 단축. 동시 사용자 증가 시 `.env`에서 `DB_MAX_CONN=20` 등으로 상향 가능 (PostgreSQL `max_connections`와 맞출 것).

### DB 연결 풀 설정·모니터링

- **설정**: `.env`의 `DB_MIN_CONN`, `DB_MAX_CONN`으로 풀 크기 지정. 기본 `DB_MAX_CONN=10`. API·백그라운드·WebSocket 등 모든 DB 접근이 이 풀을 공유하므로, 동시 요청이 많으면 풀 포화로 대기 시간이 늘어날 수 있음.
- **튜닝**: PostgreSQL `max_connections`를 넘지 않게 `DB_MAX_CONN`을 설정. 부하가 큰 경우 20~30으로 상향 검토. 앱 기동 시 로그에 `min_conn`/`max_conn`이 출력되므로 확인 가능.
- **모니터링 권장**: 풀 포화 시 요청 지연이 발생하므로, 필요 시 DB 연결 대기 시간·활성 연결 수 등을 메트릭으로 수집하는 것을 권장.
- **LLM 429 재시도**: `modules.utils.llm_retry.call_with_retry()`로 OpenAI `chat.completions.create` 호출을 래핑. 429/rate limit 시 지수 백오프+jitter로 최대 4회 재시도. RAG 추출(`rag_extractor.py`) 및 정답지·템플릿 GPT 호출(`documents.py`)에 적용됨.

## 추가로 할 수 있는 것 (비시급)

- **WebSocket 다중 워커**: `uvicorn workers >= 2` 시 ConnectionManager가 워커별로 분리되어 락/진행률이 일부 클라이언트에만 전달될 수 있음. 단일 워커 운영 또는 Redis Pub/Sub 등 공유 브로드캐스트 도입 시 해결.
- **백그라운드 업로드 순차 처리**: 한 사용자가 여러 파일 업로드 시 FastAPI BackgroundTasks는 요청 단위로 순차 실행. 체감 대기 개선 시 전용 작업 큐(Redis+RQ 등) 검토.
- **DB 풀 메트릭**: 풀 사용률·대기 시간 메트릭 수집 시 운영 중 포화 진단에 유리.

---

## 최종 진단 (적용 후)

### 해결된 항목

| 항목 | 조치 |
|------|------|
| 이벤트 루프 블로킹 (generate_page_images) | `_generate_all_page_images_sync` + `asyncio.to_thread()` |
| 이벤트 루프 블로킹 (정답지 탭 목록) | `_ensure_answer_key_designated_by_column` 호출을 `run_sync` 내부로만 이동 |
| 동시 PDF 분석 제한 | 사용자별 세마포어(1인당 1건) + 전역 상한(기본 20). `MAX_CONCURRENT_ANALYSES_PER_USER`, `MAX_CONCURRENT_ANALYSES` |
| DB 풀 가시성 | 기동 시 `min_conn`/`max_conn` 로깅, 문서화 보강 |
| LLM 429 대응 | `call_with_retry()` 적용 (RAG 추출 + 정답지/GPT 템플릿 호출) |

### 남은 이슈 (우선순위 낮음)

| 이슈 | 영향 | 권장 |
|------|------|------|
| WebSocket 다중 워커 불일치 | workers≥2일 때 락/진행률이 일부 클라이언트에만 전달 가능 | 단일 워커 또는 Redis Pub/Sub |
| 백그라운드 업로드 순차 처리 | 한 사용자 다건 업로드 시 대기 시간 증가 | 필요 시 작업 큐 도입 |
| RAG 검색 직렬화(_search_lock) | 동시 분석 시 RAG 대기열 증가 | 현 구조 유지(안정성 우선) |
| 디스크 I/O 제한 없음 | 동시 분석 시 같은 디스크 경합 가능 | 동시 분석 수 제한으로 완화됨 |
