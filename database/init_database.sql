-- ============================================
-- 조건청구서 파싱 시스템 PostgreSQL 데이터베이스 초기화 스크립트
-- 프로젝트 이관 시 최초 DB 생성용
-- current/archive 테이블만 생성 (원본 테이블 없음)
-- ============================================

-- ============================================
-- 1. 사용자 관리 테이블 (필수)
-- ============================================

-- 사용자 테이블
CREATE TABLE users (
    user_id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(200) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
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

-- ============================================
-- 2. 문서 메타데이터 테이블 (current/archive)
-- ============================================

-- documents_current 테이블
CREATE TABLE documents_current (
    document_id SERIAL PRIMARY KEY,
    pdf_filename VARCHAR(500) UNIQUE NOT NULL,
    form_type VARCHAR(10),
    total_pages INTEGER,
    parsing_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_year INTEGER,
    data_month INTEGER,
    created_by_user_id INTEGER REFERENCES users(user_id),
    updated_by_user_id INTEGER REFERENCES users(user_id)
);

-- documents_archive 테이블
CREATE TABLE documents_archive (
    document_id SERIAL PRIMARY KEY,
    pdf_filename VARCHAR(500) UNIQUE NOT NULL,
    form_type VARCHAR(10),
    total_pages INTEGER,
    parsing_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_year INTEGER,
    data_month INTEGER,
    created_by_user_id INTEGER REFERENCES users(user_id),
    updated_by_user_id INTEGER REFERENCES users(user_id)
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
    product_name VARCHAR(500),
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
    product_name VARCHAR(500),
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

CREATE TABLE rag_vector_index (
    index_id SERIAL PRIMARY KEY,
    index_name VARCHAR(100) NOT NULL DEFAULT 'base',
    form_type VARCHAR(10) NOT NULL,
    index_data BYTEA NOT NULL,
    metadata_json JSONB NOT NULL,
    index_size BIGINT,
    vector_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(index_name, form_type)
);

-- ============================================
-- 9. 인덱스 생성
-- ============================================

-- documents_current 인덱스
CREATE INDEX idx_documents_current_pdf_filename ON documents_current(pdf_filename);
CREATE INDEX idx_documents_current_timestamp ON documents_current(parsing_timestamp DESC);
CREATE INDEX idx_documents_current_form_type ON documents_current(form_type);
CREATE INDEX idx_documents_current_year_month ON documents_current(data_year, data_month);
CREATE INDEX idx_documents_current_created_by_user ON documents_current(created_by_user_id);
CREATE INDEX idx_documents_current_updated_by_user ON documents_current(updated_by_user_id);

-- documents_archive 인덱스
CREATE INDEX idx_documents_archive_pdf_filename ON documents_archive(pdf_filename);
CREATE INDEX idx_documents_archive_timestamp ON documents_archive(parsing_timestamp DESC);
CREATE INDEX idx_documents_archive_form_type ON documents_archive(form_type);
CREATE INDEX idx_documents_archive_year_month ON documents_archive(data_year, data_month);
CREATE INDEX idx_documents_archive_created_by_user ON documents_archive(created_by_user_id);
CREATE INDEX idx_documents_archive_updated_by_user ON documents_archive(updated_by_user_id);

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
CREATE INDEX idx_items_current_product ON items_current(product_name);
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
CREATE INDEX idx_items_archive_product ON items_archive(product_name);
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

-- users 인덱스
CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_is_active ON users(is_active);

-- user_sessions 인덱스
CREATE INDEX idx_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX idx_user_sessions_expires_at ON user_sessions(expires_at);

-- ============================================
-- 10. 함수 생성
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
-- 초기화 완료
-- ============================================
