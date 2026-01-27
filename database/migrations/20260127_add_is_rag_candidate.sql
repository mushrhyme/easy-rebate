-- 페이지 단위 RAG 학습 플래그 컬럼 추가

ALTER TABLE page_data_current
  ADD COLUMN IF NOT EXISTS is_rag_candidate BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE page_data_archive
  ADD COLUMN IF NOT EXISTS is_rag_candidate BOOLEAN NOT NULL DEFAULT FALSE;

