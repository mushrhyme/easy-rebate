-- ============================================
-- 조건청구서 파싱 시스템 PostgreSQL 데이터베이스 초기화 스크립트
-- 프로젝트 이관 시 최초 DB 생성용
-- current/archive 테이블만 생성 (원본 테이블 없음)
-- ============================================

-- ============================================
-- 1. 사용자 관리 테이블 (필수)
-- ============================================

-- 사용자 테이블 (로그인ID.xlsx 전체 컬럼 반영)
CREATE TABLE users (
    user_id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(200) NOT NULL,
    display_name_ja VARCHAR(200),
    department_ko VARCHAR(200),
    department_ja VARCHAR(200),
    role VARCHAR(100),
    category VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    is_admin BOOLEAN DEFAULT FALSE,
    password_hash VARCHAR(255),
    force_password_change BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP,
    login_count INTEGER DEFAULT 0,
    created_by_user_id INTEGER REFERENCES users(user_id)
);

-- 사용자 세션 테이블
CREATE TABLE user_sessions (
    session_id VARCHAR(255) PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP + INTERVAL '24 hours'),
    ip_address VARCHAR(45),
    user_agent TEXT
);

-- pg_trgm: 슈퍼명 유사도 검색(90% 이상)용 (retail_user.csv 기반 담당 필터에 사용)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================
-- 2. 문서 메타데이터 테이블 (current/archive)
-- ============================================

-- documents_current 테이블
CREATE TABLE documents_current (
    document_id SERIAL PRIMARY KEY,
    pdf_filename VARCHAR(500) UNIQUE NOT NULL,
    form_type VARCHAR(10),
    upload_channel VARCHAR(20),
    document_metadata JSONB,
    total_pages INTEGER,
    parsing_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_year INTEGER,
    data_month INTEGER,
    is_answer_key_document BOOLEAN NOT NULL DEFAULT FALSE,
    created_by_user_id INTEGER REFERENCES users(user_id),
    updated_by_user_id INTEGER REFERENCES users(user_id),
    answer_key_designated_by_user_id INTEGER REFERENCES users(user_id)
);

-- documents_archive 테이블
CREATE TABLE documents_archive (
    document_id SERIAL PRIMARY KEY,
    pdf_filename VARCHAR(500) UNIQUE NOT NULL,
    form_type VARCHAR(10),
    upload_channel VARCHAR(20),
    document_metadata JSONB,
    total_pages INTEGER,
    parsing_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_year INTEGER,
    data_month INTEGER,
    is_answer_key_document BOOLEAN NOT NULL DEFAULT FALSE,
    created_by_user_id INTEGER REFERENCES users(user_id),
    updated_by_user_id INTEGER REFERENCES users(user_id),
    answer_key_designated_by_user_id INTEGER REFERENCES users(user_id)
);

-- ============================================
-- 3. 페이지 데이터 테이블 (current/archive)
-- ============================================

-- page_data_current 테이블
CREATE TABLE page_data_current (
    page_data_id SERIAL PRIMARY KEY,
    pdf_filename VARCHAR(500) NOT NULL REFERENCES documents_current(pdf_filename) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    page_role VARCHAR(50),
    page_meta JSONB,
    -- 이 페이지를 벡터DB(RAG) 학습에 사용할지 여부 (관리자 화면에서 토글)
    is_rag_candidate BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(pdf_filename, page_number)
);

-- page_data_archive 테이블
CREATE TABLE page_data_archive (
    page_data_id SERIAL PRIMARY KEY,
    pdf_filename VARCHAR(500) NOT NULL REFERENCES documents_archive(pdf_filename) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    page_role VARCHAR(50),
    page_meta JSONB,
    -- 아카이브 테이블에도 동일한 플래그 유지
    is_rag_candidate BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(pdf_filename, page_number)
);

-- ============================================
-- 4. 행 단위 데이터 테이블 (current/archive)
-- ============================================

-- items_current 테이블
CREATE TABLE items_current (
    item_id SERIAL PRIMARY KEY,
    pdf_filename VARCHAR(500) NOT NULL,
    page_number INTEGER NOT NULL,
    item_order INTEGER NOT NULL CHECK (item_order > 0),
    customer VARCHAR(255),
    first_review_checked BOOLEAN DEFAULT FALSE,
    second_review_checked BOOLEAN DEFAULT FALSE,
    first_reviewed_at TIMESTAMP,
    second_reviewed_at TIMESTAMP,
    item_data JSONB NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by_user_id INTEGER REFERENCES users(user_id),
    updated_by_user_id INTEGER REFERENCES users(user_id),
    first_reviewed_by_user_id INTEGER REFERENCES users(user_id),
    second_reviewed_by_user_id INTEGER REFERENCES users(user_id),
    FOREIGN KEY (pdf_filename, page_number) 
        REFERENCES page_data_current(pdf_filename, page_number) 
        ON DELETE CASCADE
);

-- items_archive 테이블
CREATE TABLE items_archive (
    item_id SERIAL PRIMARY KEY,
    pdf_filename VARCHAR(500) NOT NULL,
    page_number INTEGER NOT NULL,
    item_order INTEGER NOT NULL CHECK (item_order > 0),
    customer VARCHAR(255),
    first_review_checked BOOLEAN DEFAULT FALSE,
    second_review_checked BOOLEAN DEFAULT FALSE,
    first_reviewed_at TIMESTAMP,
    second_reviewed_at TIMESTAMP,
    item_data JSONB NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by_user_id INTEGER REFERENCES users(user_id),
    updated_by_user_id INTEGER REFERENCES users(user_id),
    first_reviewed_by_user_id INTEGER REFERENCES users(user_id),
    second_reviewed_by_user_id INTEGER REFERENCES users(user_id),
    FOREIGN KEY (pdf_filename, page_number) 
        REFERENCES page_data_archive(pdf_filename, page_number) 
        ON DELETE CASCADE
);

-- ============================================
-- 5. 행 단위 편집 락 테이블 (current/archive)
-- ============================================

-- item_locks_current 테이블
CREATE TABLE item_locks_current (
    item_id INTEGER PRIMARY KEY REFERENCES items_current(item_id) ON DELETE CASCADE,
    locked_by_user_id INTEGER NOT NULL REFERENCES users(user_id),
    locked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL
);

-- item_locks_archive 테이블
CREATE TABLE item_locks_archive (
    item_id INTEGER PRIMARY KEY REFERENCES items_archive(item_id) ON DELETE CASCADE,
    locked_by_user_id INTEGER NOT NULL REFERENCES users(user_id),
    locked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL
);

-- ============================================
-- 6. 페이지 이미지 테이블 (current/archive)
-- ============================================

-- page_images_current 테이블 (image_data 제외)
CREATE TABLE page_images_current (
    image_id SERIAL PRIMARY KEY,
    pdf_filename VARCHAR(500) NOT NULL REFERENCES documents_current(pdf_filename) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    image_path VARCHAR(500),
    image_format VARCHAR(10) DEFAULT 'JPEG',
    image_size INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(pdf_filename, page_number)
);

-- page_images_archive 테이블 (image_data 제외)
CREATE TABLE page_images_archive (
    image_id SERIAL PRIMARY KEY,
    pdf_filename VARCHAR(500) NOT NULL REFERENCES documents_archive(pdf_filename) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    image_path VARCHAR(500),
    image_format VARCHAR(10) DEFAULT 'JPEG',
    image_size INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(pdf_filename, page_number)
);

-- ============================================
-- 7. RAG 학습 상태 테이블 (current/archive)
-- ============================================

-- rag_learning_status_current 테이블
CREATE TABLE rag_learning_status_current (
    learning_id SERIAL PRIMARY KEY,
    pdf_filename VARCHAR(500) NOT NULL,
    page_number INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    page_hash VARCHAR(64),
    fingerprint_mtime REAL,
    fingerprint_size INTEGER,
    shard_id VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(pdf_filename, page_number)
);

-- rag_learning_status_archive 테이블
CREATE TABLE rag_learning_status_archive (
    learning_id SERIAL PRIMARY KEY,
    pdf_filename VARCHAR(500) NOT NULL,
    page_number INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    page_hash VARCHAR(64),
    fingerprint_mtime REAL,
    fingerprint_size INTEGER,
    shard_id VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(pdf_filename, page_number)
);

-- ============================================
-- 8. RAG 벡터 인덱스 테이블 (필수)
-- ============================================

-- 단일 글로벌 벡터 인덱스만 사용 (양식별 인덱스 없음). form_type은 NULL 또는 '' = 글로벌.
CREATE TABLE rag_vector_index (
    index_id SERIAL PRIMARY KEY,
    index_name VARCHAR(100) NOT NULL DEFAULT 'base',
    form_type VARCHAR(10),
    index_data BYTEA NOT NULL,
    metadata_json JSONB NOT NULL,
    index_size BIGINT,
    vector_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(index_name, form_type)
);

-- ============================================
-- 9. 필드 매핑 테이블 (논리키 → 양식별 실제 필드명)
-- ============================================

CREATE TABLE form_field_mappings (
    id SERIAL PRIMARY KEY,
    form_code VARCHAR(10) NOT NULL,
    logical_key VARCHAR(100) NOT NULL,
    physical_key VARCHAR(255) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(form_code, logical_key)
);

-- 기본값 시드 (거래처는 코드에서 항상 得意先로 통일, customer 매핑 없음)
INSERT INTO form_field_mappings (form_code, logical_key, physical_key, is_active)
VALUES
    ('01', 'customer_code', '得意先CD', TRUE),
    ('02', 'customer_code', '得意先CD', TRUE),
    ('03', 'customer_code', '得意先CD', TRUE),
    ('04', 'customer_code', '得意先CD', TRUE),
    ('05', 'customer_code', '得意先CD', TRUE),
    ('01', 'management_id', '請求伝票番号', TRUE),
    ('02', 'management_id', '請求No（契約No）', TRUE),
    ('03', 'management_id', '請求No', TRUE),
    ('04', 'management_id', '管理No', TRUE),
    ('05', 'management_id', '照会番号', TRUE),
    ('01', 'summary', '備考', TRUE),
    ('03', 'summary', '摘要', TRUE),
    ('01', 'tax', '消費税率', TRUE),
    ('03', 'tax', '税額', TRUE);

-- 様式コードの表示名（基準管理：01→条件① 等を任意の名前に変更可能）
CREATE TABLE form_type_labels (
    form_code VARCHAR(10) PRIMARY KEY,
    display_name VARCHAR(200) NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- 10. 인덱스 생성
-- ============================================

-- documents_current 인덱스
CREATE INDEX idx_documents_current_pdf_filename ON documents_current(pdf_filename);
CREATE INDEX idx_documents_current_timestamp ON documents_current(parsing_timestamp DESC);
CREATE INDEX idx_documents_current_form_type ON documents_current(form_type);
CREATE INDEX idx_documents_current_upload_channel ON documents_current(upload_channel);
CREATE INDEX idx_documents_current_year_month ON documents_current(data_year, data_month);
CREATE INDEX idx_documents_current_created_by_user ON documents_current(created_by_user_id);
CREATE INDEX idx_documents_current_updated_by_user ON documents_current(updated_by_user_id);
CREATE INDEX idx_documents_current_is_answer_key ON documents_current(is_answer_key_document) WHERE is_answer_key_document = TRUE;

-- documents_archive 인덱스
CREATE INDEX idx_documents_archive_pdf_filename ON documents_archive(pdf_filename);
CREATE INDEX idx_documents_archive_timestamp ON documents_archive(parsing_timestamp DESC);
CREATE INDEX idx_documents_archive_form_type ON documents_archive(form_type);
CREATE INDEX idx_documents_archive_upload_channel ON documents_archive(upload_channel);
CREATE INDEX idx_documents_archive_year_month ON documents_archive(data_year, data_month);
CREATE INDEX idx_documents_archive_created_by_user ON documents_archive(created_by_user_id);
CREATE INDEX idx_documents_archive_updated_by_user ON documents_archive(updated_by_user_id);
CREATE INDEX idx_documents_archive_is_answer_key ON documents_archive(is_answer_key_document) WHERE is_answer_key_document = TRUE;

-- page_data_current 인덱스
CREATE INDEX idx_page_data_current_pdf_filename ON page_data_current(pdf_filename);
CREATE INDEX idx_page_data_current_pdf_page ON page_data_current(pdf_filename, page_number);

-- page_data_archive 인덱스
CREATE INDEX idx_page_data_archive_pdf_filename ON page_data_archive(pdf_filename);
CREATE INDEX idx_page_data_archive_pdf_page ON page_data_archive(pdf_filename, page_number);

-- items_current 인덱스
CREATE INDEX idx_items_current_pdf_page ON items_current(pdf_filename, page_number);
CREATE INDEX idx_items_current_pdf_page_order ON items_current(pdf_filename, page_number, item_order);
CREATE INDEX idx_items_current_customer ON items_current(customer);
CREATE INDEX idx_items_current_first_review ON items_current(first_review_checked);
CREATE INDEX idx_items_current_second_review ON items_current(second_review_checked);
CREATE INDEX idx_items_current_data_gin ON items_current USING GIN (item_data);
CREATE INDEX idx_items_current_created_by_user ON items_current(created_by_user_id);
CREATE INDEX idx_items_current_updated_by_user ON items_current(updated_by_user_id);
CREATE INDEX idx_items_current_first_reviewed_by_user ON items_current(first_reviewed_by_user_id);
CREATE INDEX idx_items_current_second_reviewed_by_user ON items_current(second_reviewed_by_user_id);

-- items_archive 인덱스
CREATE INDEX idx_items_archive_pdf_page ON items_archive(pdf_filename, page_number);
CREATE INDEX idx_items_archive_pdf_page_order ON items_archive(pdf_filename, page_number, item_order);
CREATE INDEX idx_items_archive_customer ON items_archive(customer);
CREATE INDEX idx_items_archive_first_review ON items_archive(first_review_checked);
CREATE INDEX idx_items_archive_second_review ON items_archive(second_review_checked);
CREATE INDEX idx_items_archive_data_gin ON items_archive USING GIN (item_data);
CREATE INDEX idx_items_archive_created_by_user ON items_archive(created_by_user_id);
CREATE INDEX idx_items_archive_updated_by_user ON items_archive(updated_by_user_id);
CREATE INDEX idx_items_archive_first_reviewed_by_user ON items_archive(first_reviewed_by_user_id);
CREATE INDEX idx_items_archive_second_reviewed_by_user ON items_archive(second_reviewed_by_user_id);

-- item_locks_current 인덱스
CREATE INDEX idx_item_locks_current_expires_at ON item_locks_current(expires_at);
CREATE INDEX idx_item_locks_current_locked_by_user ON item_locks_current(locked_by_user_id);

-- item_locks_archive 인덱스
CREATE INDEX idx_item_locks_archive_expires_at ON item_locks_archive(expires_at);
CREATE INDEX idx_item_locks_archive_locked_by_user ON item_locks_archive(locked_by_user_id);

-- page_images_current 인덱스
CREATE INDEX idx_page_images_current_pdf_filename ON page_images_current(pdf_filename);
CREATE INDEX idx_page_images_current_pdf_page ON page_images_current(pdf_filename, page_number);

-- page_images_archive 인덱스
CREATE INDEX idx_page_images_archive_pdf_filename ON page_images_archive(pdf_filename);
CREATE INDEX idx_page_images_archive_pdf_page ON page_images_archive(pdf_filename, page_number);

-- rag_learning_status_current 인덱스
CREATE INDEX idx_rag_learning_status_current_pdf_page ON rag_learning_status_current(pdf_filename, page_number);
CREATE INDEX idx_rag_learning_status_current_status ON rag_learning_status_current(status);
CREATE INDEX idx_rag_learning_status_current_hash ON rag_learning_status_current(page_hash);

-- rag_learning_status_archive 인덱스
CREATE INDEX idx_rag_learning_status_archive_pdf_page ON rag_learning_status_archive(pdf_filename, page_number);
CREATE INDEX idx_rag_learning_status_archive_status ON rag_learning_status_archive(status);
CREATE INDEX idx_rag_learning_status_archive_hash ON rag_learning_status_archive(page_hash);

-- rag_vector_index 인덱스
CREATE INDEX idx_rag_vector_index_name ON rag_vector_index(index_name);
CREATE INDEX idx_rag_vector_index_form_type ON rag_vector_index(form_type);
CREATE INDEX idx_rag_vector_index_name_form ON rag_vector_index(index_name, form_type);

-- form_field_mappings 인덱스
CREATE INDEX idx_form_field_mappings_form_code ON form_field_mappings(form_code);
CREATE INDEX idx_form_field_mappings_logical_key ON form_field_mappings(logical_key);
CREATE INDEX idx_form_field_mappings_is_active ON form_field_mappings(is_active);

-- users 인덱스
CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_is_active ON users(is_active);

-- user_sessions 인덱스
CREATE INDEX idx_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX idx_user_sessions_expires_at ON user_sessions(expires_at);

-- ============================================
-- 11. 함수 생성
-- ============================================

-- 만료된 락 정리 함수 (current + archive 모두 처리)
CREATE OR REPLACE FUNCTION cleanup_expired_locks()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM item_locks_current
    WHERE expires_at < CURRENT_TIMESTAMP;
    
    DELETE FROM item_locks_archive
    WHERE expires_at < CURRENT_TIMESTAMP;
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- 만료된 세션 정리 함수
CREATE OR REPLACE FUNCTION cleanup_expired_sessions()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM user_sessions
    WHERE expires_at < CURRENT_TIMESTAMP;

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- ============================================
-- 로그인ID.xlsx → users 반영 (CSV 있으면 실행)
-- ============================================
-- 먼저: python -m database.export_users_csv 로 database/csv/users_import.csv 생성 (해당 스크립트 있을 경우)
-- 프로젝트 루트에서 실행: psql -U postgres -d rebate_db -f database/init_database.sql
-- CSV 8열: 빈열, ID, 이름(한글), 名前, 부서명(한글), 部署, 권한, 분류

CREATE TEMP TABLE _users_csv (
    col_1 TEXT,
    col_2 TEXT,
    col_3 TEXT,
    col_4 TEXT,
    col_5 TEXT,
    col_6 TEXT,
    col_7 TEXT,
    col_8 TEXT
);

\copy _users_csv (col_1, col_2, col_3, col_4, col_5, col_6, col_7, col_8) FROM 'database/csv/users_import.csv' WITH (FORMAT csv, HEADER true);

INSERT INTO users (username, display_name, display_name_ja, department_ko, department_ja, role, category, is_active)
SELECT
    trim(col_2),
    COALESCE(NULLIF(trim(col_3), ''), NULLIF(trim(col_4), ''), trim(col_2)),
    NULLIF(trim(col_4), ''),
    NULLIF(trim(col_5), ''),
    NULLIF(trim(col_6), ''),
    NULLIF(trim(col_7), ''),
    NULLIF(trim(col_8), ''),
    TRUE
FROM _users_csv
WHERE col_2 IS NOT NULL AND trim(col_2) <> ''
ON CONFLICT (username) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    display_name_ja = EXCLUDED.display_name_ja,
    department_ko = EXCLUDED.department_ko,
    department_ja = EXCLUDED.department_ja,
    role = EXCLUDED.role,
    category = EXCLUDED.category,
    is_active = EXCLUDED.is_active;

-- ============================================
-- 거래처 검색 속도: ILIKE/부분일치용 트리그램 인덱스 (pg_trgm)
-- ============================================
CREATE INDEX IF NOT EXISTS idx_items_current_customer_expr_trgm
  ON items_current USING gin ((COALESCE(NULLIF(trim(item_data->>'得意先'), ''), NULLIF(trim(customer), ''), '')) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_items_archive_customer_expr_trgm
  ON items_archive USING gin ((COALESCE(NULLIF(trim(item_data->>'得意先'), ''), NULLIF(trim(customer), ''), '')) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_items_current_item_data_text_trgm
  ON items_current USING gin ((item_data::text) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_items_archive_item_data_text_trgm
  ON items_archive USING gin ((item_data::text) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_page_data_current_page_meta_trgm
  ON page_data_current USING gin ((page_meta::text) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_page_data_archive_page_meta_trgm
  ON page_data_archive USING gin ((page_meta::text) gin_trgm_ops);

-- ============================================
-- 초기화 완료 (담당·슈퍼는 database/csv/retail_user.csv 등 CSV만 사용、DB 테이블 없음)
-- ============================================
