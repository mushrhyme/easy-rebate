# 리팩토링 시스템 스펙 (백엔드·프론트 공통)

- **프로세스·요구사항 기준**: `to_do.md` 참조.
- **벡터 DB (현재)**: **pgvector**(`rag_page_embeddings`) 사용. RAG 검색·학습 요청은 pgvector 기준. FAISS는 폴백 및 기존 빌드 스크립트용.
- **구현 단계**: Phase 1 → Phase 2 → Phase 3. (Phase 2 pgvector 전환 적용됨.)

**화면 구분**: **검토 탭** = 検索 탭(CustomerSearch). 문서 목록·선택·페이지 이동·편집·저장·재분석·학습 요청은 여기서 수행. **페이지 이동은 분석을 자동 실행하지 않음. 분석은 버튼으로만 실행**(이 페이지 재분석 / 이 페이지 이후 전체 재분석). **解答作成 탭** = 검토 탭에서 「解答作成」 클릭 시 **그 한 페이지만** 브릿지로 표시하는 화면(AnswerKeyTab). 단일 페이지 전용, 페이지 이동·자동 분석 없음.

---

## 1. Phase 구분


| Phase       | 범위                                     | 요약 (현재 구현 반영)                                                                                                                                          |
| ----------- | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| **Phase 1** | 업로드·검토 탭 동작 + 단일/일괄 분석 API + 페이지 히스토리 DB | **현재**: 업로드 시 이미지 생성 후 **전체 페이지** OCR+RAG+LLM 분석, 페이지 완료 시마다 DB 저장. **페이지 전환 시 자동 분석 없음**. 분석은 버튼 2종: 이 페이지 재분석 / 이 페이지 이후 전체 재분석(병렬). 단일 페이지 분석 API·이 페이지 이후 전체 재분석 API 구현됨. 검토 탭 저장은 **편집 중인 행만 행 단위 PATCH**. 解答作成은 한 페이지만 브릿지, 해당 페이지만 PUT answer-json. DB 스키마(ocr_text, analyzed_vector_version, last_analyzed_at, current_vector_version 등)는 `init_database.sql`에 반영. |
| **Phase 2** | pgvector 전환                            | **적용됨.** RAG 검색·학습 요청은 pgvector(`rag_page_embeddings`) 사용. FAISS는 폴백.                                                                     |
| **Phase 3** | UI 정리·예외 처리                            | form_type 수동 변경/재검출 UI 제거, 별도 학습 요청 탭 제거, 페이지 히스토리 표시 UI, 예외 처리 정리.                                                               |


---

## 2. API (신규·변경·유지)

### 2.1 백엔드


| 구분          | 메서드/경로 (예시)                                              | 설명                                                                                                                                                                                                                             |
| ----------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **신규**      | `POST /api/documents/analyze-single-page` (또는 기존 경로에 쿼리) | 단일 페이지 분석(재분석). 요청: pdf_filename, page_number. 응답: 해당 페이지 분석 결과. 내부: **OCR은 DB에서 읽음**(재실행 없음) → RAG 검색(현재 벡터 DB) → LLM → 결과 반환 후 해당 페이지만 DB 저장(analyzed_vector_version, last_analyzed_at 갱신). |
| **신규**      | `POST /api/documents/analyze-from-page` (이 페이지 이후 전체 재분석) | 요청: pdf_filename, from_page_number. 해당 페이지~마지막 페이지까지 **병렬** 재분석(동시도 상한 예: 3~5). 각 페이지: OCR DB 사용 → RAG+LLM → DB 저장. 진행 중 동일 문서에 대해 학습 요청 시 이 재분석은 **중단**. |
| **신규**      | 단일 페이지 저장 / 행 단위 저장                                                | **解答作成 탭**: 해당 (pdf_filename, page_number)만 PUT answer-json으로 page_data/items upsert. **검토 탭**: 편집 중인 행만 **행 단위 PATCH**로 저장. 저장 시 last_edited_at 등 갱신.                                                                            |
| **신규**      | `POST /api/.../learning-request-page` (단일 페이지 학습 요청)     | **현재**: 해당 페이지만 pgvector(`rag_page_embeddings`)에 INSERT/UPDATE. 처리 직후 **current_vector_version +1**. 해당 문서에 이 페이지 이후 전체 재분석 진행 중이면 먼저 재분석 중단 후 학습 반영. |
| **변경**      | 업로드 API                                                  | **현재**: PDF → 이미지 생성·저장 + **전체 페이지** OCR+RAG+LLM 분석, 페이지 완료 시마다 DB 저장(page_data_current.ocr_text, page_meta, items 등). form_type은 분석 결과 기준 설정. 실패 시 문서만 생성, form_type null. **재분석** 시 OCR은 DB에서만 읽음. |
| **변경**      | 검토 탭 문서/페이지 조회                                           | 기존 get_document, get_page_result 등 유지. **페이지 전환 시 분석 자동 호출 없음**. OCR·기존 분석 결과만 반환. 분석은 사용자가 버튼으로만 요청.                                                                                                                                                                   |
| **Phase 2** | 벡터 검색/저장/교체                                              | RAG 검색: pgvector에서 유사 벡터 조회. 학습 요청: pgvector에 insert 또는 (pdf, page) 기준 update. 문서/페이지별 analyzed_vector_version, current_vector_version 관리.                                                                                                                                                 |


### 2.2 프론트


| 화면                 | 동작                                                                                                                  | 호출                                                                                              |
| ------------------ | ------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| 업로드 탭              | PDF 업로드                                                                                                             | 업로드 API(이미지+**전체 페이지** OCR·분석, 페이지 완료 시마다 DB 저장). 성공 시 문서 목록 갱신.                                                           |
| 검토 탭 목록            | form_type·연월 필터                                                                                                     | 기존 문서 목록 API. form_type null 허용(1페이지 분석 실패 시).                                                  |
| 검토 탭 문서 열기         | 문서 선택 시 이미지·페이지별 데이터 로드                                                                                             | 기존 get_document, get_page_result(또는 페이지별 결과 조회).                                                |
| 검토 탭(検索) 페이지 전환        | **페이지 이동은 분석을 실행하지 않음.** 해당 페이지 OCR·기존 분석 결과만 조회하여 표시. 분석이 필요하면 사용자가 **버튼**으로만 실행: **このページ再分析**(현재 페이지만) 또는 **このページ以降の全ページを再分析**(현재~마지막, 병렬). (解答作成 탭에는 페이지 전환·자동 분석 없음) | GET 문서/페이지 조회. 분석 시에만 POST analyze-single-page 또는 analyze-from-page.                                                       |
| 검토 탭 재분석 버튼        | **このページ再分析**: 현재 페이지만 재분석. **このページ以降の全ページを再分析**: 현재 페이지~마지막까지 병렬 재분석(진행률 표시). 재분석 진행 중 학습 요청 시 서버에서 진행 중 재분석 중단 후 학습 반영.                                                                 | POST analyze-single-page / analyze-from-page.                                                       |
| 검토 탭 저장            | 保存 버튼 또는 Ctrl+S                                                                                                     | **현재**: 편집 중인 **행(item)만** 행 단위 PATCH로 저장. 解答作成 탭에서는 해당 페이지만 PUT answer-json 호출.                   |
| 검토 탭 학습 요청         | 관리자만 보이는 학습 요청 버튼                                                                                                   | 편집 중 dirty 있으면 「저장 후 학습 요청해주세요」 alert 후 중단. 없으면 learning-request-page API 호출. 재분석(이 페이지 이후 전체) 진행 중이면 호출 시 서버가 재분석 중단 후 학습 반영. |
| (Phase 3) 페이지 히스토리 | 해당 페이지 수정 여부·학습 요청 여부 표시                                                                                            | page_data.last_edited_at, page_data.is_rag_candidate(및 필요 시 last_edited_by) 조회하여 표시.            |


---

## 3. DB 스키마

### 3.1 기존 테이블 변경

- **page_data_current** (또는 page_data_archive 동일 적용) — **`init_database.sql`에 반영됨**
  - `page_number`, `page_role`, `page_meta`, `ocr_text`, `analyzed_vector_version`, `last_analyzed_at`
  - `last_edited_at` TIMESTAMPTZ NULL, `last_edited_by_user_id` INTEGER NULL
  - `is_rag_candidate` BOOLEAN — 학습 요청 시 TRUE, 재학습 시에도 유지.
- **documents_current** — **`init_database.sql`에 반영됨**
  - `form_type`, `total_pages`, `current_vector_version`
  - 업로드·분석 실패 시 form_type NULL 허용.

※ first_reviewed_at / first_review_checked 등은 1차·2차 **검토 체크**용으로 유지. 그리드 셀 편집(保存) 이력과는 별개.

### 3.2 pgvector (Phase 2) — `init_database.sql`에 포함

- **테이블**: `rag_page_embeddings`. 페이지 단위 임베딩 1개 = 1행.
- **핵심 컬럼 예시**
  - `id` (PK)
  - `pdf_filename` (또는 document_id), `page_number` — 문서·페이지 식별
  - `ocr_text` TEXT — 임베딩 시 사용한 OCR 텍스트
  - `embedding` vector(n) — pgvector 타입
  - `answer_json` JSONB — 해당 페이지 정답 JSON(검색 시 예제로 사용)
  - `form_type` VARCHAR(2) — 검색 필터용
  - `updated_at` TIMESTAMPTZ
- **동작**
  - 학습 요청(첫 추가): INSERT.
  - 재학습(같은 pdf_filename + page_number): 해당 행 UPDATE(embedding, ocr_text, answer_json 등 갱신). 삭제 후 재삽입도 가능.
  - 검색: `WHERE form_type = ?` 등 적용 후 `ORDER BY embedding <=> query_embedding LIMIT k`.

---

## 4. 백엔드 모듈별 요약


| 구분             | 내용                                                                                                                                                       |
| -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 업로드            | **현재**: PDF 수신 → 이미지 생성·저장 → **전체 페이지** OCR+RAG+LLM 분석, 페이지 완료 시마다 DB 저장. form_type은 분석 결과 기준. 실패 시 문서만 생성, form_type null. **재분석** 시 OCR은 DB에서만 읽음. |
| 단일 페이지 분석      | **OCR은 DB에서 읽음** → RAG 검색(현재 벡터 DB) → LLM → 결과 반환 + 해당 페이지만 DB 저장(analyzed_vector_version, last_analyzed_at 갱신).                                                                               |
| 이 페이지 이후 전체 재분석 | (pdf_filename, from_page_number) 요청 시 해당 페이지~마지막 페이지 **병렬** 재분석(동시도 상한 예: 3~5). 각 페이지: OCR DB 사용 → RAG+LLM → DB 저장. **진행 중 동일 문서에 학습 요청 시 이 재분석 중단.**               |
| 단일 페이지 저장 / 행 저장      | 解答作成: 해당 페이지만 PUT answer-json. 검토 탭: 편집 중인 행만 행 단위 PATCH. last_edited_at 등 갱신.               |
| 학습 요청 | **현재**: pgvector (pdf_filename, page_number) 기준 INSERT/UPDATE. **current_vector_version +1.** 해당 문서 재분석 진행 중이면 먼저 중단.                                                           |
| RAG 검색         | **현재**: pgvector `<=>` 검색. form_type 필터. 실패 시 FAISS 폴백.                                                                                                   |


---

## 5. 프론트 모듈별 요약


| 구분               | 내용                                                                                                  |
| ---------------- | --------------------------------------------------------------------------------------------------- |
| 업로드 탭            | 업로드 후 전체 OCR+1·2페이지만 분석 완료까지 표시 후 문서 목록 갱신. (전체 분석 대기 없음.)                                                 |
| 검토 탭 문서 목록       | form_type null 표시(미분류) 허용. 기존 필터 유지.                                                                |
| 검토 탭(検索) 페이지 뷰       | **페이지 전환 시 분석 자동 실행 없음.** 해당 페이지 OCR·기존 분석 결과만 조회하여 표시. 분석은 **버튼 2종**으로만: **このページ再分析**(현재 페이지만), **このページ以降の全ページを再分析**(현재~마지막, 병렬·진행률 표시). 解答作成 탭은 브릿지된 한 페이지만 표시, 페이지 이동·자동 분석 없음.      |
| 검토 탭 저장          | 保存 / Ctrl+S → **현재**: 편집 중인 **행만** 행 단위 PATCH. 解答作成 탭에서는 해당 페이지만 PUT answer-json.           |
| 검토 탭 학습 요청       | 버튼 클릭 시 dirty 여부 확인 → 있으면 alert 후 중단. 없으면 learning-request-page 호출. 재분석(이 페이지 이후 전체) 진행 중이어도 호출 가능 → 서버에서 재분석 중단 후 학습 반영.                                 |
| Phase 3: 히스토리 표시 | 페이지별로 last_edited_at / is_rag_candidate 표시(수정함·학습 요청함 등). form_type 수동 변경/재검출 UI 제거. 별도 학습 요청 탭 제거. |


---

## 6. 예외·에러 처리


| 상황              | 처리                                                              |
| --------------- | --------------------------------------------------------------- |
| 업로드 1·2페이지 분석 실패  | 문서는 생성, form_type은 null. 검토 탭 목록에서 form_type 미분류로 표시.           |
| 편집 중 학습 요청 클릭   | 저장 안 된 수정 있으면 「저장 후 학습 요청해주세요」 alert, API 미호출. |
| 재분석(이 페이지 이후 전체) 진행 중 학습 요청 | 해당 문서의 진행 중인 재분석을 **중단**한 뒤 학습 반영. 필요 시 사용자가 이후 다시 재분석 버튼 실행.                       |
| 단일 페이지 분석 실패    | 에러 메시지 반환, 프론트에서 토스트/alert. DB는 기존 값 유지.                        |
| 학습 요청(벡터 반영) 실패 | 에러 반환, is_rag_candidate 롤백 여부는 정책에 따라 결정.                       |


---

## 7. 구현 순서 (Phase별) — 현재 상태

**Phase 1** (대부분 반영됨)

1. DB: **`init_database.sql`에 반영됨.** page_data_current(ocr_text, analyzed_vector_version, last_analyzed_at, last_edited_at, last_edited_by_user_id), documents_current(current_vector_version).
2. 백엔드: 업로드 — **현재** 이미지 생성 + **전체 페이지** OCR+RAG+LLM, 페이지 완료 시마다 DB 저장. (목표였던 1·2페이지만 초기 분석은 미적용.)
3. 단일 페이지 분석 API, 이 페이지 이후 전체 재분석 API(병렬·중단 처리) 구현됨.
4. 학습 요청: pgvector 사용으로 Phase 2와 동일하게 동작.
5. 프론트: 검토 탭 페이지 전환 시 자동 분석 없음, 버튼 2종. 검토 탭 저장은 편집 행만 PATCH. 학습 요청 시 dirty 체크·alert.

**Phase 2** (적용됨)

1. pgvector 확장·`rag_page_embeddings` 테이블 — `init_database.sql`에 포함.
2. RAG 검색: pgvector 사용. 실패 시 FAISS 폴백.
3. 학습 요청: pgvector insert/update. current_vector_version +1.

**Phase 3**

1. form_type 수동 변경·재검출 UI 제거.
2. 별도 학습 요청 탭(ベクターDB反映) 제거.
3. 페이지 히스토리(last_edited_at, is_rag_candidate) 표시 UI 추가.
4. 예외 메시지·에러 처리 정리.

