# 데이터베이스 스키마 문서

## 개요

조건청구서 파싱 시스템의 PostgreSQL 데이터베이스 스키마입니다. 현재연월용(`*_current`)과 아카이브용(`*_archive`) 테이블로 분리되어 있으며, 매월 자동으로 아카이브 마이그레이션이 수행됩니다.

## 테이블 구조

### 1. 문서 메타데이터 테이블

#### `documents` (원본 테이블)
- **용도**: PDF 파일 기본 정보 저장
- **주요 컬럼**:
  - `document_id`: 문서 고유 ID (PRIMARY KEY)
  - `pdf_filename`: PDF 파일명 (UNIQUE, NOT NULL)
  - `form_type`: 양식지 번호 (01, 02, 03, 04, 05)
  - `total_pages`: 총 페이지 수
  - `data_year`, `data_month`: 연월 (아카이브 분리용)

#### `documents_current` / `documents_archive`
- **구조**: `documents`와 동일 + `is_answer_key_document`
- **용도**: 현재연월 데이터는 `*_current`, 과거 데이터는 `*_archive`에 저장
- **is_answer_key_document**: 정답지 생성 대상 여부 (TRUE면 검토 탭에서 제외, 정답지 생성 탭에서만 표시)

### 2. 페이지 데이터 테이블

#### `page_data` (원본 테이블)
- **용도**: 페이지 메타데이터 저장 (items 제외)
- **주요 컬럼**:
  - `page_data_id`: 페이지 데이터 고유 ID (PRIMARY KEY)
  - `pdf_filename`: PDF 파일명 (외래키 → documents.pdf_filename)
  - `page_number`: 페이지 번호 (1부터 시작)
  - `page_role`: 페이지 역할 (cover, detail, summary, reply)
  - `page_meta`: 페이지 메타데이터 (JSONB)
- **제약조건**: `UNIQUE(pdf_filename, page_number)`

#### `page_data_current` / `page_data_archive`
- **구조**: `page_data`와 동일
- **외래키**: 
  - `page_data_current.pdf_filename` → `documents_current.pdf_filename`
  - `page_data_archive.pdf_filename` → `documents_archive.pdf_filename`

### 3. 행 단위 데이터 테이블

#### `items` (원본 테이블)
- **용도**: 개별 행 데이터 저장
- **주요 컬럼**:
  - `item_id`: 행 고유 ID (PRIMARY KEY)
  - `pdf_filename`, `page_number`: 페이지 식별자
  - `item_order`: UI 정렬용 순서
  - `customer`: 거래처명 (공통 필드). 상품명은 `item_data->'商品名'` 사용
  - `first_review_checked`, `second_review_checked`: 검토 상태
  - `item_data`: 양식지별 필드 (JSONB)
  - `version`: 낙관적 락용 버전
- **외래키**: `(pdf_filename, page_number)` → `page_data(pdf_filename, page_number)`

#### `items_current` / `items_archive`
- **구조**: `items`와 동일
- **외래키**:
  - `items_current` → `page_data_current`
  - `items_archive` → `page_data_archive`

### 4. 행 단위 편집 락 테이블

#### `item_locks` (원본 테이블)
- **용도**: 행 편집 락 관리
- **주요 컬럼**:
  - `item_id`: 행 ID (PRIMARY KEY, 외래키 → items.item_id)
  - `locked_by_user_id`: 락을 획득한 사용자 ID
  - `locked_at`: 락 획득 시각
  - `expires_at`: 락 만료 시각

#### `item_locks_current` / `item_locks_archive`
- **구조**: 동일
- **외래키**:
  - `item_locks_current.item_id` → `items_current.item_id`
  - `item_locks_archive.item_id` → `items_archive.item_id`

### 5. 페이지 이미지 테이블

#### `page_images` (원본 테이블)
- **용도**: 페이지 이미지 저장
- **주요 컬럼**:
  - `image_id`: 이미지 고유 ID (PRIMARY KEY)
  - `pdf_filename`: PDF 파일명 (외래키 → documents.pdf_filename)
  - `page_number`: 페이지 번호
  - `image_path`: 이미지 파일 경로 (파일 시스템 저장 시)
  - `image_data`: 이미지 데이터 (BYTEA, 하위 호환성용)
- **제약조건**: `UNIQUE(pdf_filename, page_number)`

#### `page_images_current` / `page_images_archive`
- **구조**: `image_data` 컬럼 제외 (파일 시스템 저장 방식 사용)
- **외래키**:
  - `page_images_current.pdf_filename` → `documents_current.pdf_filename`
  - `page_images_archive.pdf_filename` → `documents_archive.pdf_filename`

### 6. RAG 학습 상태 테이블

#### `rag_learning_status` (원본 테이블)
- **용도**: 벡터DB 학습 상태 관리
- **주요 컬럼**:
  - `learning_id`: 학습 상태 고유 ID (PRIMARY KEY)
  - `pdf_filename`, `page_number`: 페이지 식별자
  - `status`: 상태 (pending, staged, merged, deleted)
  - `page_hash`: 페이지 해시 (SHA256)
  - `fingerprint_mtime`, `fingerprint_size`: 파일 fingerprint
  - `shard_id`: Shard ID
- **제약조건**: `UNIQUE(pdf_filename, page_number)`

#### `rag_learning_status_current` / `rag_learning_status_archive`
- **구조**: `rag_learning_status`와 동일

### 7. RAG 벡터 인덱스 테이블

#### `rag_vector_index`
- **용도**: FAISS 벡터 인덱스 저장 (단일 글로벌 인덱스만 사용, 양식별 인덱스 없음)
- **주요 컬럼**:
  - `index_id`: 인덱스 고유 ID (PRIMARY KEY)
  - `index_name`: 인덱스명 (`base` = 글로벌, `shard_*` = 병합 전 샤드)
  - `form_type`: NULL = 글로벌 인덱스 (nullable)
  - `index_data`: FAISS 인덱스 데이터 (BYTEA)
  - `metadata_json`: 메타데이터 (JSONB)
  - `vector_count`: 벡터 수
- **제약조건**: `UNIQUE(index_name, form_type)`
- **참고**: 검색은 항상 전체 양식 통합(글로벌)으로 수행되며, 예제 메타데이터 내 `form_type`으로만 구분 가능
- **기존 DB 마이그레이션**: `form_type`이 NOT NULL이면 `ALTER TABLE rag_vector_index ALTER COLUMN form_type DROP NOT NULL;` 실행 후, 기존 `base_01`/`base_02` 등은 무시되고 새로 쌓이는 데이터는 `(base, NULL)` 한 행만 사용됨

### 8. 필드 매핑 테이블

#### `form_field_mappings`
- **용도**: 빈값 채우기·RAG 등에서 사용하는 논리키(예: customer, management_id)와 양식별(form_code) 실제 필드명(physical_key) 매핑. DB 우선 조회, 없으면 config fallback. (상품명은 item_data 내 商品名만 사용, product_name 논리키 제거됨)
- **주요 컬럼**:
  - `id`: PK
  - `form_code`: 양식 코드 (01, 02, 03, 04, 05)
  - `logical_key`: 논리 키 (customer, customer_code, management_id, summary, tax 등)
  - `physical_key`: 해당 양식에서의 실제 필드명 (예: 得意先名, 商品名)
  - `is_active`: 사용 여부
  - `created_at`, `updated_at`
- **제약조건**: `UNIQUE(form_code, logical_key)`
- **관리**: 관리자 전용 API/UI에서 CRUD 가능 (비개발자가 웹에서 수정 가능).

### 9. 사용자 관리 테이블

#### `users`
- **용도**: 사용자 정보 저장
- **주요 컬럼**:
  - `user_id`: 사용자 고유 ID (PRIMARY KEY)
  - `username`: 로그인 ID (UNIQUE, NOT NULL)
  - `display_name`: 표시 이름
  - `is_active`: 활성 상태
  - `last_login_at`: 마지막 로그인 시간
  - `login_count`: 로그인 횟수

#### `user_sessions`
- **용도**: 사용자 세션 관리
- **주요 컬럼**:
  - `session_id`: 세션 ID (PRIMARY KEY)
  - `user_id`: 사용자 ID (외래키 → users.user_id)
  - `expires_at`: 세션 만료 시각
  - `ip_address`, `user_agent`: 접속 정보

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

## 인덱스

### 주요 인덱스
- **문서 조회**: `pdf_filename`, `form_type`, `data_year, data_month`
- **페이지 조회**: `(pdf_filename, page_number)`
- **행 검색**: `customer`, `item_data` (GIN, 상품명은 item_data->'商品名' 사용)
- **검토 상태**: `first_review_checked`, `second_review_checked`
- **락 관리**: `expires_at`, `locked_by_user_id`

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

테이블 삭제는 관리자가 DBeaver 등에서 직접 수행. 테이블 생성은 `init_database.sql` 만 실행:
```bash
psql -U postgres -d rebate_db -f database/init_database.sql
```

## 검증

스키마 검증 스크립트:
```bash
python3 database/verify_schema.py
```
