-- ============================================
-- 사용자 테이블 복구 스크립트
-- users 테이블이 삭제되었거나 데이터가 없을 때 사용
-- ============================================

-- 사용자 테이블이 없으면 생성
CREATE TABLE IF NOT EXISTS users (
    user_id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(200) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP,
    login_count INTEGER DEFAULT 0,
    created_by_user_id INTEGER REFERENCES users(user_id)
);

-- 사용자 세션 테이블이 없으면 생성
CREATE TABLE IF NOT EXISTS user_sessions (
    session_id VARCHAR(255) PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP + INTERVAL '24 hours'),
    ip_address VARCHAR(45),
    user_agent TEXT
);

-- 초기 관리자 사용자 생성 (이미 존재하면 무시)
-- username: admin, display_name: 관리자
INSERT INTO users (username, display_name, is_active)
VALUES ('admin', '관리자', TRUE)
ON CONFLICT (username) DO NOTHING;

-- 사용 예시: 다른 사용자 추가
INSERT INTO users (username, display_name, is_active, created_by_user_id)
VALUES ('user1', '사용자1', TRUE, 1)
ON CONFLICT (username) DO NOTHING;
