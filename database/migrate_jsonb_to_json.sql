-- 기존 DB: JSONB → JSON 컬럼 타입 변경 (키 순서 유지용)
-- 신규 설치 시에는 init_database.sql 사용. 이미 떠 있는 DB에만 이 스크립트 실행.

-- documents
ALTER TABLE documents_current
  ALTER COLUMN document_metadata TYPE json USING document_metadata::text::json;
ALTER TABLE documents_archive
  ALTER COLUMN document_metadata TYPE json USING document_metadata::text::json;

-- page_data
ALTER TABLE page_data_current
  ALTER COLUMN page_meta TYPE json USING page_meta::text::json;
ALTER TABLE page_data_archive
  ALTER COLUMN page_meta TYPE json USING page_meta::text::json;

-- items
ALTER TABLE items_current
  ALTER COLUMN item_data TYPE json USING item_data::text::json;
ALTER TABLE items_archive
  ALTER COLUMN item_data TYPE json USING item_data::text::json;

-- RAG (테이블이 있을 때만 ALTER 실행, 없으면 스킵)
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'rag_vector_index') THEN
    ALTER TABLE rag_vector_index ALTER COLUMN metadata_json TYPE json USING metadata_json::text::json;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'rag_page_embeddings') THEN
    ALTER TABLE rag_page_embeddings ALTER COLUMN answer_json TYPE json USING answer_json::text::json;
  END IF;
END $$;
