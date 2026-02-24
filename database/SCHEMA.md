# 데이터베이스 스키마 문서

## 개요

조건청구서 파싱 시스템의 PostgreSQL 데이터베이스 스키마입니다. **현재연월용(`*_current`)과 아카이브용(`*_archive`) 테이블만 생성**하며(원본 단일 테이블 없음), 매월 자동으로 아카이브 마이그레이션이 수행됩니다.

## database 폴더 구조

| 경로 | 설명 |
|------|------|
| `database/` | 스키마·초기화 스크립트·DB 접속/테이블 선택 로직 (Python 모듈) |
| `database/init_database.sql` | 테이블·인덱스·함수 생성 및 사용자 시드 (`\copy` 시 `database/csv/users_import.csv` 사용) |
| `database/csv/` | CSV 데이터 전용 (retail_user, dist_retail, unit_price, users_import). 상세는 `database/csv/README.md` 참고 |

## 테이블 구조

### 1. 문서 메타데이터 테이블

#### `documents_current` / `documents_archive`
- **용도**: PDF 파일 기본 정보 저장. 현재연월은 `*_current`, 과거 데이터는 `*_archive`.
- **주요 컬럼**:
  - `document_id`: 문서 고유 ID (PRIMARY KEY)
  - `pdf_filename`: PDF 파일명 (UNIQUE, NOT NULL)
  - `form_type`: 양식지 번호 (01, 02, 03, 04, 05)
  - `upload_channel`: 업로드 채널
  - `document_metadata`: 문서 메타데이터 (JSONB)
  - `total_pages`: 총 페이지 수
  - `parsing_timestamp`, `notes`, `created_at`, `updated_at`
  - `data_year`, `data_month`: 연월 (아카이브 분리용)
  - `is_answer_key_document`: 정답지 생성 대상 여부 (TRUE면 검토 탭에서 제외, 정답지 생성 탭에서만 표시)
  - `created_by_user_id`, `updated_by_user_id`, `answer_key_designated_by_user_id`: 사용자 참조 (→ users.user_id)

### 2. 페이지 데이터 테이블

#### `page_data_current` / `page_data_archive`
- **용도**: 페이지 메타데이터 저장 (items 제외).
- **주요 컬럼**:
  - `page_data_id`: 페이지 데이터 고유 ID (PRIMARY KEY)
  - `pdf_filename`: PDF 파일명 (외래키 → documents_*)
  - `page_number`: 페이지 번호 (1부터 시작)
  - `page_role`: 페이지 역할 (cover, detail, summary, reply)
  - `page_meta`: 페이지 메타데이터 (JSONB)
  - `is_rag_candidate`: RAG 학습 대상 여부 (관리자 화면 토글)
  - `created_at`, `updated_at`
- **제약조건**: `UNIQUE(pdf_filename, page_number)`
- **외래키**: `pdf_filename` → `documents_current` / `documents_archive`

### 3. 행 단위 데이터 테이블

#### `items_current` / `items_archive`
- **용도**: 개별 행 데이터 저장.
- **주요 컬럼**:
  - `item_id`: 행 고유 ID (PRIMARY KEY)
  - `pdf_filename`, `page_number`: 페이지 식별자 (FK → page_data_*)
  - `item_order`: UI 정렬용 순서 (CHECK > 0)
  - `customer`: 거래처명 (공통 필드). 상품명은 `item_data->'商品名'` 사용
  - `first_review_checked`, `second_review_checked`: 검토 상태
  - `first_reviewed_at`, `second_reviewed_at`: 검토 시각
  - `item_data`: 양식지별 필드 (JSONB)
  - `version`: 낙관적 락용 버전
  - `created_at`, `updated_at`, `created_by_user_id`, `updated_by_user_id`, `first_reviewed_by_user_id`, `second_reviewed_by_user_id`: 사용자 참조 (→ users.user_id)
- **외래키**: `(pdf_filename, page_number)` → `page_data_current` / `page_data_archive`

### 4. 행 단위 편집 락 테이블

#### `item_locks_current` / `item_locks_archive`
- **용도**: 행 편집 락 관리.
- **주요 컬럼**: `item_id` (PK, FK → items_*.item_id), `locked_by_user_id`, `locked_at`, `expires_at`
- **외래키**: `item_id` → `items_current` / `items_archive`

### 5. 페이지 이미지 테이블

#### `page_images_current` / `page_images_archive`
- **용도**: 페이지 이미지 경로 저장 (파일 시스템 저장 방식, BYTEA 없음).
- **주요 컬럼**: `image_id` (PK), `pdf_filename` (FK → documents_*), `page_number`, `image_path`, `image_format`, `image_size`, `created_at`
- **제약조건**: `UNIQUE(pdf_filename, page_number)`

### 6. RAG 학습 상태 테이블

#### `rag_learning_status_current` / `rag_learning_status_archive`
- **용도**: 벡터DB 학습 상태 관리.
- **주요 컬럼**: `learning_id` (PK), `pdf_filename`, `page_number`, `status` (pending/staged/merged/deleted), `page_hash`, `fingerprint_mtime`, `fingerprint_size`, `shard_id`, `created_at`, `updated_at`
- **제약조건**: `UNIQUE(pdf_filename, page_number)`

### 7. RAG 벡터 인덱스 테이블

#### `rag_vector_index`
- **용도**: FAISS 벡터 인덱스 저장 (단일 글로벌 인덱스만 사용, 양식별 인덱스 없음).
- **주요 컬럼**: `index_id` (PK), `index_name` (기본 `base`), `form_type` (NULL = 글로벌), `index_data` (BYTEA), `metadata_json` (JSONB), `index_size`, `vector_count`, `created_at`, `updated_at`
- **제약조건**: `UNIQUE(index_name, form_type)`
- **참고**: 검색은 글로벌로 수행되며, 예제 메타데이터 내 `form_type`으로 구분. 기존 `form_type` NOT NULL이면 `ALTER COLUMN form_type DROP NOT NULL` 후 `(base, NULL)` 한 행만 사용.

### 8. 필드 매핑 테이블

#### `form_field_mappings`
- **용도**: 논리키(customer_code, management_id 등)와 양식별(form_code) 실제 필드명(physical_key) 매핑. DB 우선, 없으면 config fallback. (상품명은 item_data 내 商品名만 사용.)
- **주요 컬럼**: `id` (PK), `form_code`, `logical_key`, `physical_key`, `is_active`, `created_at`, `updated_at`
- **제약조건**: `UNIQUE(form_code, logical_key)`. 관리자 API/UI에서 CRUD 가능.

#### `form_type_labels`
- **용도**: 양식 코드의 표시명 관리 (예: 01 → 조건①). API/관리 화면에서 표시명 변경 가능.
- **주요 컬럼**: `form_code` (PK), `display_name`, `updated_at`

### 9. 사용자 관리 테이블

#### `users`
- **용도**: 사용자 정보 저장 (로그인ID.xlsx 기반 가져오기 지원).
- **주요 컬럼**:
  - `user_id` (PK), `username` (UNIQUE, NOT NULL), `display_name`, `display_name_ja`, `department_ko`, `department_ja`, `role`, `category`
  - `is_active`, `is_admin` (관리자 여부, 기준관리 탭에서 계정별 부여), `password_hash`, `force_password_change`, `created_at`, `last_login_at`, `login_count`, `created_by_user_id` (FK → users)
- **관리자 판별**: `username = 'admin'` 이거나 `is_admin = TRUE` 이면 관리자. 기존 DB는 `database/migrations/add_is_admin.sql` 실행 후 `username='admin'` 사용자에 `is_admin=TRUE` 설정됨.

#### `user_sessions`
- **용도**: 사용자 세션 관리.
- **주요 컬럼**: `session_id` (PK), `user_id` (FK → users), `created_at`, `expires_at`, `ip_address`, `user_agent`

## 외래키 제약조건

### 현재연월용 테이블
- `page_data_current.pdf_filename` → `documents_current.pdf_filename`
- `items_current(pdf_filename, page_number)` → `page_data_current(pdf_filename, page_number)`
- `page_images_current.pdf_filename` → `documents_current.pdf_filename`
- `item_locks_current.item_id` → `items_current.item_id`

### 아카이브용 테이블
- `page_data_archive.pdf_filename` → `documents_archive.pdf_filename`
- `items_archive(pdf_filename, page_number)` → `page_data_archive(pdf_filename, page_number)`
- `page_images_archive.pdf_filename` → `documents_archive.pdf_filename`
- `item_locks_archive.item_id` → `items_archive.item_id`

## 확장 및 인덱스

- **pg_trgm**: `CREATE EXTENSION IF NOT EXISTS pg_trgm` — 슈퍼명/담당 유사도 검색(ILIKE, 90% 이상) 및 거래처 부분일치용. `database/csv/retail_user.csv` 기반 담당 필터에 사용.

### 주요 인덱스
- **문서**: `pdf_filename`, `form_type`, `upload_channel`, `data_year, data_month`, `parsing_timestamp`, `created_by_user_id`, `updated_by_user_id`, `is_answer_key_document` (partial)
- **페이지**: `(pdf_filename, page_number)`, `page_meta` (GIN trgm)
- **행**: `customer`, `item_data` (GIN), `first_review_checked`, `second_review_checked`, created/updated/first_reviewed/second_reviewed_by_user_id, 거래처/전문 trgm (COALESCE(item_data->>'得意先', customer), item_data::text)
- **락/세션**: `expires_at`, `locked_by_user_id`

## 함수

### `cleanup_expired_locks()`
- **용도**: 만료된 락 정리
- **반환값**: 삭제된 락 개수

### `cleanup_expired_sessions()`
- **용도**: 만료된 세션 정리
- **반환값**: 삭제된 세션 개수

## 데이터 저장 방식

### 현재연월 데이터
- 모든 새로 업로드된 문서는 `*_current` 테이블에 저장
- 매월 1일 0시에 자동으로 이전 달 데이터가 `*_archive`로 이동

### 아카이브 데이터
- 과거 데이터는 `*_archive` 테이블에 저장
- 조회 시 `*_current`와 `*_archive`를 모두 검색

## 초기화

- 테이블 삭제는 관리자가 DBeaver 등에서 직접 수행.
- 테이블·인덱스·함수 생성: `init_database.sql` 실행.
```bash
psql -U postgres -d rebate_db -f database/init_database.sql
```
- 사용자 시드: `database/csv/users_import.csv`가 있으면 동일 스크립트에서 `\copy`로 `users`에 반영 (로그인ID.xlsx → CSV export 후 8열 형식).
- 담당·슈퍼 정보는 DB 테이블 없이 `database/csv/retail_user.csv` 등 CSV만 사용.
