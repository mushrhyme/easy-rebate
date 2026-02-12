"""
RAG (Retrieval-Augmented Generation) 관리 모듈

FAISS를 사용하여 OCR 텍스트와 정답 JSON 쌍을 저장하고 검색합니다.
"""

import os
import json
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from threading import Lock
import faiss
import ssl
import urllib3

# SSL 인증서 검증 비활성화 (프록시/자체 서명 인증서 환경 대응)
# 내부 네트워크 환경에서 Hugging Face 모델 다운로드 시 필요
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
ssl._create_default_https_context = ssl._create_unverified_context

# 환경 변수 설정
os.environ.setdefault("PYTHONHTTPSVERIFY", "0")
os.environ.setdefault("CURL_CA_BUNDLE", "")
os.environ.setdefault("REQUESTS_CA_BUNDLE", "")

# httpx 클라이언트 SSL 검증 비활성화 (huggingface_hub가 httpx를 사용)
try:
    import httpx
    # httpx 클라이언트의 기본 verify 값을 False로 설정
    original_client_init = httpx.Client.__init__
    original_async_client_init = httpx.AsyncClient.__init__
    
    def patched_client_init(self, *args, verify=None, **kwargs):
        if verify is None:
            verify = False
        return original_client_init(self, *args, verify=verify, **kwargs)
    
    def patched_async_client_init(self, *args, verify=None, **kwargs):
        if verify is None:
            verify = False
        return original_async_client_init(self, *args, verify=verify, **kwargs)
    
    httpx.Client.__init__ = patched_client_init
    httpx.AsyncClient.__init__ = patched_async_client_init
except ImportError:
    # httpx가 설치되지 않은 경우 무시
    pass
except Exception as e:
    # 패치 실패해도 계속 진행
    print(f"⚠️ httpx SSL 패치 중 경고 (무시 가능): {e}")


class RAGManager:
    """
    RAG 벡터 DB 관리 클래스
    
    FAISS를 사용하여 OCR 텍스트를 임베딩하고 검색합니다.
    """
    
    _model_lock = Lock()
    
    def __init__(self, persist_directory: Optional[str] = None, use_db: bool = True):
        self.use_db = use_db
        
        if persist_directory is None:
            from modules.utils.config import get_project_root
            project_root = get_project_root()
            persist_directory = str(project_root / "rag_db")
        
        self.persist_directory = persist_directory
        
        if self.use_db:
            from database.registry import get_db
            import psycopg2
            self.db = get_db()
            self._ensure_vector_index_table_exists()
        else:
            os.makedirs(persist_directory, exist_ok=True, mode=0o755)
            self.base_index_path = os.path.join(persist_directory, "base.faiss")
            self.base_metadata_path = os.path.join(persist_directory, "base_metadata.json")
        
        self._embedding_model = None
        self.index = None
        self.metadata = {}
        self.id_to_index = {}
        self.index_to_id = {}
        self._load_index()
        self._bm25_index = None
        self._bm25_texts = None
        self._bm25_example_map = None
    
    def _get_embedding_model(self):
        if self._embedding_model is None:
            with RAGManager._model_lock:
                if self._embedding_model is None:
                    try:
                        # Tokenizers 병렬 처리 비활성화
                        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
                        
                        from sentence_transformers import SentenceTransformer
                        self._embedding_model = SentenceTransformer(
                            'paraphrase-multilingual-MiniLM-L12-v2'
                        )
                    except ImportError:
                        raise ImportError(
                            "sentence-transformers가 설치되지 않았습니다.\n"
                            "다음 명령어로 설치하세요: pip install sentence-transformers"
                        )
        return self._embedding_model
    
    def _get_embedding_dim(self) -> int:
        model = self._get_embedding_model()
        test_embedding = model.encode(["test"], convert_to_numpy=True)
        return test_embedding.shape[1]
    
    def _load_index(self):
        embedding_dim = self._get_embedding_dim()
        
        if self.use_db:
            self.index, self.metadata, self.id_to_index, self.index_to_id = self._load_index_from_db()
            if self.index is None:
                self.index = faiss.IndexFlatL2(embedding_dim)
                self.metadata = {}
                self.id_to_index = {}
                self.index_to_id = {}
        else:
            if os.path.exists(self.base_index_path):
                try:
                    self.index = faiss.read_index(self.base_index_path)
                except Exception as e:
                    print(f"⚠️ FAISS 인덱스 로드 실패, 새로 생성: {e}")
                    self.index = faiss.IndexFlatL2(embedding_dim)
            else:
                self.index = faiss.IndexFlatL2(embedding_dim)
            self.metadata, self.id_to_index, self.index_to_id = self._load_metadata_from_file(self.base_metadata_path)
        
        if len(self.index_to_id) < len(self.id_to_index):
            self.index_to_id = {idx: doc_id for doc_id, idx in self.id_to_index.items()}
            self._save_index()
    
    def reload_index(self):
        self._load_index()
        self._refresh_bm25_index()
        self.count_examples()
    
    def _ensure_vector_index_table_exists(self):
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = 'rag_vector_index'
                    )
                """)
                table_exists = cursor.fetchone()[0]
                
                if not table_exists:
                    cursor.execute("""
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
                        )
                    """)
                    cursor.execute("""
                        CREATE INDEX idx_rag_vector_index_name 
                        ON rag_vector_index(index_name)
                    """)
                    cursor.execute("""
                        CREATE INDEX idx_rag_vector_index_form_type 
                        ON rag_vector_index(form_type)
                    """)
                    cursor.execute("""
                        CREATE INDEX idx_rag_vector_index_name_form 
                        ON rag_vector_index(index_name, form_type)
                    """)
                else:
                    cursor.execute("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.columns 
                            WHERE table_name = 'rag_vector_index' 
                            AND column_name = 'form_type'
                        )
                    """)
                    has_form_type = cursor.fetchone()[0]
                    if not has_form_type:
                        cursor.execute("""
                            ALTER TABLE rag_vector_index 
                            ADD COLUMN form_type VARCHAR(10)
                        """)
                        cursor.execute("""
                            ALTER TABLE rag_vector_index 
                            DROP CONSTRAINT IF EXISTS rag_vector_index_index_name_key
                        """)
                        cursor.execute("""
                            ALTER TABLE rag_vector_index 
                            ADD CONSTRAINT rag_vector_index_index_name_form_type_key 
                            UNIQUE (index_name, form_type)
                        """)
                        cursor.execute("""
                            CREATE INDEX IF NOT EXISTS idx_rag_vector_index_form_type 
                            ON rag_vector_index(form_type)
                        """)
                        cursor.execute("""
                            CREATE INDEX IF NOT EXISTS idx_rag_vector_index_name_form 
                            ON rag_vector_index(index_name, form_type)
                        """)
        except Exception as e:
            print(f"⚠️ 테이블 생성 중 오류 발생: {e}")
    
    def _load_index_from_db(self, form_type: Optional[str] = None) -> Tuple[Optional[Any], Dict[str, Any], Dict[str, int], Dict[int, str]]:
        """
        DB에서 FAISS 인덱스를 로드합니다. 단일 글로벌 인덱스만 사용합니다.
        1) index_name='base', form_type IS NULL/'' 인 행이 있으면 사용
        2) 없으면 shard_* 전체를 병합해 (base, NULL)로 저장 후 반환
        (form_type 인자는 하위 호환용으로 무시)
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()

                # 1) 글로벌 base 인덱스 로드
                cursor.execute("""
                    SELECT index_data, metadata_json, vector_count
                    FROM rag_vector_index
                    WHERE index_name = 'base' AND (form_type IS NULL OR form_type = '')
                    ORDER BY updated_at DESC
                    LIMIT 1
                """)
                row = cursor.fetchone()
                if row and len(row) >= 3:
                    index_data_bytes, metadata_json, vector_count = row[0], row[1], row[2] or 0
                    if isinstance(index_data_bytes, memoryview):
                        index_data_bytes = np.frombuffer(index_data_bytes, dtype=np.uint8)
                    elif isinstance(index_data_bytes, bytes):
                        index_data_bytes = np.frombuffer(index_data_bytes, dtype=np.uint8)
                    else:
                        index_data_bytes = np.frombuffer(bytes(index_data_bytes), dtype=np.uint8)
                    index = faiss.deserialize_index(index_data_bytes)
                    metadata = metadata_json.get('metadata', {})
                    id_to_index = metadata_json.get('id_to_index', {})
                    index_to_id_raw = metadata_json.get('index_to_id', {})
                    index_to_id = {int(k): v for k, v in index_to_id_raw.items()}
                    return index, metadata, id_to_index, index_to_id

                # 2) base 없으면 shard_* 전체 병합 후 (base, NULL)로 저장
                cursor.execute("""
                    SELECT index_data, metadata_json, vector_count, index_name
                    FROM rag_vector_index
                    WHERE index_name LIKE 'shard_%'
                    ORDER BY updated_at DESC
                """)
                shard_rows = cursor.fetchall()
                if not shard_rows or len(shard_rows[0]) < 4:
                    return None, {}, {}, {}

                def _bytes_to_np(b):
                    if isinstance(b, memoryview):
                        return np.frombuffer(b, dtype=np.uint8)
                    if isinstance(b, bytes):
                        return np.frombuffer(b, dtype=np.uint8)
                    return np.frombuffer(bytes(b), dtype=np.uint8)

                first_data, first_meta, _, _ = shard_rows[0]
                base_index = faiss.deserialize_index(_bytes_to_np(first_data))
                base_metadata = first_meta.get('metadata', {})
                base_id_to_index = first_meta.get('id_to_index', {})
                base_index_to_id_raw = first_meta.get('index_to_id', {})
                base_index_to_id = {int(k): v for k, v in base_index_to_id_raw.items()}

                for shard_row in shard_rows[1:]:
                    if len(shard_row) < 4:
                        continue
                    shard_data_bytes, shard_metadata_json, _, _ = shard_row
                    shard_index = faiss.deserialize_index(_bytes_to_np(shard_data_bytes))
                    base_vector_count = base_index.ntotal
                    base_index.merge_from(shard_index)
                    shard_metadata = shard_metadata_json.get('metadata', {})
                    shard_id_to_index = shard_metadata_json.get('id_to_index', {})
                    shard_index_to_id_raw = shard_metadata_json.get('index_to_id', {})
                    shard_index_to_id = {int(k): v for k, v in shard_index_to_id_raw.items()}
                    for doc_id, shard_faiss_idx in shard_id_to_index.items():
                        new_faiss_idx = base_vector_count + shard_faiss_idx
                        base_metadata[doc_id] = shard_metadata.get(doc_id, {})
                        base_id_to_index[doc_id] = new_faiss_idx
                        base_index_to_id[new_faiss_idx] = doc_id

                total_vectors = base_index.ntotal
                try:
                    self._save_merged_index_to_db(base_index, base_metadata, base_id_to_index, base_index_to_id, total_vectors, None)
                except Exception as save_err:
                    print(f"⚠️ base 인덱스 저장 실패 (계속 사용 가능): {save_err}")
                return base_index, base_metadata, base_id_to_index, base_index_to_id

        except Exception as e:
            print(f"⚠️ DB에서 인덱스 로드 실패: {e}")
            import traceback
            traceback.print_exc()
            return None, {}, {}, {}
    
    def _load_metadata_from_file(self, metadata_path: str) -> Tuple[Dict[str, Any], Dict[str, int], Dict[int, str]]:
        if not os.path.exists(metadata_path):
            return {}, {}, {}
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                metadata = data.get("metadata", {})
                id_to_index = data.get("id_to_index", {})
                index_to_id_raw = data.get("index_to_id", {})
                index_to_id = {int(k): v for k, v in index_to_id_raw.items()}
                return metadata, id_to_index, index_to_id
        except Exception as e:
            print(f"⚠️ 메타데이터 로드 실패: {e}")
            return {}, {}, {}
    
    def _save_index(self):
        try:
            if self.use_db:
                self._save_index_to_db()
            else:
                faiss.write_index(self.index, self.base_index_path)
                data = {
                    "metadata": self.metadata,
                    "id_to_index": self.id_to_index,
                    "index_to_id": self.index_to_id
                }
                with open(self.base_metadata_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 인덱스 저장 실패: {e}")
    
    def _save_merged_index_to_db(
        self,
        index: Any,
        metadata: Dict[str, Any],
        id_to_index: Dict[str, int],
        index_to_id: Dict[int, str],
        vector_count: int,
        form_type: Optional[str] = None
    ):
        """단일 글로벌 인덱스만 (base, NULL)로 저장합니다."""
        try:
            serialized = faiss.serialize_index(index)
            if hasattr(serialized, 'tobytes'):
                index_data_bytes = serialized.tobytes()
            else:
                index_data_bytes = bytes(serialized)
            index_size = len(index_data_bytes)
            def clean_for_json(obj):
                import math
                if isinstance(obj, dict):
                    return {k: clean_for_json(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [clean_for_json(item) for item in obj]
                elif isinstance(obj, float):
                    if math.isnan(obj) or math.isinf(obj):
                        return None
                    return obj
                return obj
            cleaned_metadata = clean_for_json(metadata)
            metadata_json = {
                "metadata": cleaned_metadata,
                "id_to_index": id_to_index,
                "index_to_id": {str(k): v for k, v in index_to_id.items()}
            }
            base_index_name = 'base'
            form_type_value = ''  # NULL이면 UNIQUE/ON CONFLICT 미동작하므로 '' 사용
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO rag_vector_index (
                        index_name, form_type, index_data, metadata_json, index_size, vector_count
                    ) VALUES (%s, %s, %s, %s::jsonb, %s, %s)
                    ON CONFLICT (index_name, form_type)
                    DO UPDATE SET
                        index_data = EXCLUDED.index_data,
                        metadata_json = EXCLUDED.metadata_json,
                        index_size = EXCLUDED.index_size,
                        vector_count = EXCLUDED.vector_count,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    base_index_name,
                    form_type_value,
                    index_data_bytes,
                    json.dumps(metadata_json, allow_nan=False),
                    index_size,
                    vector_count
                ))
        except Exception as e:
            print(f"⚠️ 병합 인덱스 저장 실패: {e}")
            raise
    
    def _save_index_to_db(self):
        try:
            serialized = faiss.serialize_index(self.index)
            if hasattr(serialized, 'tobytes'):
                index_data_bytes = serialized.tobytes()
            else:
                index_data_bytes = bytes(serialized)
            index_size = len(index_data_bytes)
            vector_count = self.index.ntotal if self.index else 0
            def clean_for_json(obj):
                import math
                if isinstance(obj, dict):
                    return {k: clean_for_json(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [clean_for_json(item) for item in obj]
                elif isinstance(obj, float):
                    if math.isnan(obj) or math.isinf(obj):
                        return None
                    return obj
                return obj
            cleaned_metadata = clean_for_json(self.metadata)
            # 단일 글로벌 인덱스만 (base, '')로 저장 (NULL이면 ON CONFLICT 미동작)
            metadata_json = {
                "metadata": cleaned_metadata,
                "id_to_index": self.id_to_index,
                "index_to_id": {str(k): v for k, v in self.index_to_id.items()}
            }
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO rag_vector_index (
                        index_name, form_type, index_data, metadata_json, index_size, vector_count
                    ) VALUES (%s, %s, %s, %s::jsonb, %s, %s)
                    ON CONFLICT (index_name, form_type)
                    DO UPDATE SET
                        index_data = EXCLUDED.index_data,
                        metadata_json = EXCLUDED.metadata_json,
                        index_size = EXCLUDED.index_size,
                        vector_count = EXCLUDED.vector_count,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    'base',
                    '',
                    index_data_bytes,
                    json.dumps(metadata_json, allow_nan=False),
                    index_size,
                    vector_count
                ))
        except Exception as e:
            print(f"⚠️ DB 인덱스 저장 실패: {e}")
            import traceback
            traceback.print_exc()
    
    def add_example(
        self,
        ocr_text: str,
        answer_json: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        skip_duplicate: bool = True
    ) -> Optional[str]:
        import uuid
        metadata = metadata or {}
        if skip_duplicate:
            pdf_name = metadata.get('pdf_name')
            page_num = metadata.get('page_num')
            if pdf_name is not None and page_num is not None:
                for existing_id, existing_data in self.metadata.items():
                    existing_metadata = existing_data.get('metadata', {})
                    if (existing_metadata.get('pdf_name') == pdf_name and 
                        existing_metadata.get('page_num') == page_num):
                        return None
        # OCR 텍스트 정규화 (반각 → 전각 변환)
        from modules.utils.text_normalizer import normalize_ocr_text
        ocr_text = normalize_ocr_text(ocr_text, use_fullwidth=True)  # 정규화된 OCR 텍스트
        
        doc_id = str(uuid.uuid4())
        model = self._get_embedding_model()
        processed_text = self.preprocess_ocr_text(ocr_text)
        embedding = model.encode([processed_text], convert_to_numpy=True).astype('float32')
        faiss_index = self.index.ntotal
        self.index.add(embedding)
        key_order = self._extract_key_order(answer_json)
        self.metadata[doc_id] = {
            "ocr_text": ocr_text,
            "answer_json": answer_json,
            "metadata": metadata,
            "key_order": key_order
        }
        self.id_to_index[doc_id] = faiss_index
        self.index_to_id[faiss_index] = doc_id
        self._save_index()
        self._refresh_bm25_index()
        return doc_id
    
    def build_shard(
        self,
        shard_pages: List[Dict[str, Any]],
        form_type: Optional[str] = None
    ) -> Optional[Tuple[str, str]]:
        """
        Shard FAISS 인덱스 생성
        
        Args:
            shard_pages: 페이지 데이터 리스트
                [{
                    'pdf_name': str,
                    'page_num': int,
                    'ocr_text': str,
                    'answer_json': Dict,
                    'metadata': Dict,
                    'page_key': str,
                    'page_hash': str
                }, ...]
            form_type: 양식지 번호 (01, 02, 03, 04, 05)
            
        Returns:
            (shard_identifier, shard_id) 튜플 또는 None
        """
        if not shard_pages:
            return None
        
        import uuid
        import time
        
        # Shard ID 생성
        shard_id = str(uuid.uuid4())
        timestamp = int(time.time())
        shard_name = f"shard_{timestamp}_{shard_id[:8]}"
        
        # 새로운 FAISS 인덱스 생성
        embedding_dim = self._get_embedding_dim()
        shard_index = faiss.IndexFlatL2(embedding_dim)
        shard_metadata = {}
        shard_id_to_index = {}
        shard_index_to_id = {}
        
        # OCR 텍스트 정규화
        from modules.utils.text_normalizer import normalize_ocr_text
        model = self._get_embedding_model()
        
        # 페이지들을 임베딩하여 추가
        for page_data in shard_pages:
            ocr_text = page_data.get('ocr_text', '')
            answer_json = page_data.get('answer_json', {})
            metadata = page_data.get('metadata', {})
            page_key = page_data.get('page_key', '')
            
            if not ocr_text:
                continue
            
            # OCR 텍스트 정규화
            normalized_text = normalize_ocr_text(ocr_text, use_fullwidth=True)
            processed_text = self.preprocess_ocr_text(normalized_text)
            
            # 임베딩 생성
            embedding = model.encode([processed_text], convert_to_numpy=True).astype('float32')
            
            # FAISS 인덱스에 추가
            faiss_idx = shard_index.ntotal
            shard_index.add(embedding)
            
            # doc_id 생성 (page_key 사용)
            doc_id = page_key if page_key else str(uuid.uuid4())
            
            # 메타데이터 저장
            key_order = self._extract_key_order(answer_json)
            shard_metadata[doc_id] = {
                "ocr_text": normalized_text,
                "answer_json": answer_json,
                "metadata": metadata,
                "key_order": key_order
            }
            shard_id_to_index[doc_id] = faiss_idx
            shard_index_to_id[faiss_idx] = doc_id
        
        if shard_index.ntotal == 0:
            return None
        
        # DB에 shard 저장
        if self.use_db:
            try:
                serialized = faiss.serialize_index(shard_index)
                if hasattr(serialized, 'tobytes'):
                    index_data_bytes = serialized.tobytes()
                else:
                    index_data_bytes = bytes(serialized)
                index_size = len(index_data_bytes)
                vector_count = shard_index.ntotal
                
                def clean_for_json(obj):
                    import math
                    if isinstance(obj, dict):
                        return {k: clean_for_json(v) for k, v in obj.items()}
                    elif isinstance(obj, list):
                        return [clean_for_json(item) for item in obj]
                    elif isinstance(obj, float):
                        if math.isnan(obj) or math.isinf(obj):
                            return None
                        return obj
                    return obj
                
                cleaned_metadata = clean_for_json(shard_metadata)
                metadata_json = {
                    "metadata": cleaned_metadata,
                    "id_to_index": shard_id_to_index,
                    "index_to_id": {str(k): v for k, v in shard_index_to_id.items()}
                }
                
                # form_type='' 로 저장 (NULL이면 UNIQUE에서 여러 행 허용 → ON CONFLICT 미동작)
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO rag_vector_index (
                            index_name, form_type, index_data, metadata_json, index_size, vector_count
                        ) VALUES (%s, %s, %s, %s::jsonb, %s, %s)
                    """, (
                        shard_name,
                        '',
                        index_data_bytes,
                        json.dumps(metadata_json, allow_nan=False),
                        index_size,
                        vector_count
                    ))
                
                return (shard_name, shard_id)
            except Exception as e:
                print(f"⚠️ Shard 저장 실패: {e}")
                import traceback
                traceback.print_exc()
                return None
        else:
            # 파일 모드 (구현 필요 시 추가)
            print("⚠️ 파일 모드의 shard 생성은 아직 지원되지 않습니다.")
            return None
    
    def merge_shard(self, shard_identifier: str) -> bool:
        """
        Shard를 base 인덱스에 병합
        
        Args:
            shard_identifier: shard 이름 (DB 모드) 또는 파일 경로 (파일 모드)
            
        Returns:
            병합 성공 여부
        """
        if not self.use_db:
            print("⚠️ 파일 모드의 shard merge는 아직 지원되지 않습니다.")
            return False
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Shard 조회
                cursor.execute("""
                    SELECT index_data, metadata_json, vector_count, form_type
                    FROM rag_vector_index
                    WHERE index_name = %s
                    ORDER BY updated_at DESC
                    LIMIT 1
                """, (shard_identifier,))
                
                row = cursor.fetchone()
                if not row:
                    print(f"⚠️ Shard를 찾을 수 없습니다: {shard_identifier}")
                    return False
                
                shard_data_bytes, shard_metadata_json, shard_vector_count, form_type = row
                
                # Shard 인덱스 역직렬화
                if isinstance(shard_data_bytes, memoryview):
                    shard_data_bytes = np.frombuffer(shard_data_bytes, dtype=np.uint8)
                elif isinstance(shard_data_bytes, bytes):
                    shard_data_bytes = np.frombuffer(shard_data_bytes, dtype=np.uint8)
                else:
                    shard_data_bytes = np.frombuffer(bytes(shard_data_bytes), dtype=np.uint8)
                
                shard_index = faiss.deserialize_index(shard_data_bytes)
                shard_metadata = shard_metadata_json.get('metadata', {})
                shard_id_to_index = shard_metadata_json.get('id_to_index', {})
                shard_index_to_id_raw = shard_metadata_json.get('index_to_id', {})
                shard_index_to_id = {int(k): v for k, v in shard_index_to_id_raw.items()}
                
                # Base 인덱스 로드 (단일 글로벌 base만 사용)
                cursor.execute("""
                    SELECT index_data, metadata_json, vector_count
                    FROM rag_vector_index
                    WHERE index_name = 'base' AND (form_type IS NULL OR form_type = '')
                    ORDER BY updated_at DESC
                    LIMIT 1
                """)
                
                base_row = cursor.fetchone()
                if base_row:
                    # 기존 base 인덱스가 있으면 로드
                    base_data_bytes, base_metadata_json, base_vector_count = base_row
                    if isinstance(base_data_bytes, memoryview):
                        base_data_bytes = np.frombuffer(base_data_bytes, dtype=np.uint8)
                    elif isinstance(base_data_bytes, bytes):
                        base_data_bytes = np.frombuffer(base_data_bytes, dtype=np.uint8)
                    else:
                        base_data_bytes = np.frombuffer(bytes(base_data_bytes), dtype=np.uint8)
                    
                    base_index = faiss.deserialize_index(base_data_bytes)
                    base_metadata = base_metadata_json.get('metadata', {})
                    base_id_to_index = base_metadata_json.get('id_to_index', {})
                    base_index_to_id_raw = base_metadata_json.get('index_to_id', {})
                    base_index_to_id = {int(k): v for k, v in base_index_to_id_raw.items()}
                else:
                    # Base 인덱스가 없으면 새로 생성
                    embedding_dim = self._get_embedding_dim()
                    base_index = faiss.IndexFlatL2(embedding_dim)
                    base_metadata = {}
                    base_id_to_index = {}
                    base_index_to_id = {}
                
                # Shard를 base에 병합
                base_vector_count_before = base_index.ntotal
                base_index.merge_from(shard_index)
                
                # 메타데이터 병합
                for doc_id, shard_faiss_idx in shard_id_to_index.items():
                    new_faiss_idx = base_vector_count_before + shard_faiss_idx
                    base_metadata[doc_id] = shard_metadata.get(doc_id, {})
                    base_id_to_index[doc_id] = new_faiss_idx
                    base_index_to_id[new_faiss_idx] = doc_id
                
                # Base 인덱스 저장
                serialized = faiss.serialize_index(base_index)
                if hasattr(serialized, 'tobytes'):
                    index_data_bytes = serialized.tobytes()
                else:
                    index_data_bytes = bytes(serialized)
                index_size = len(index_data_bytes)
                vector_count = base_index.ntotal
                
                def clean_for_json(obj):
                    import math
                    if isinstance(obj, dict):
                        return {k: clean_for_json(v) for k, v in obj.items()}
                    elif isinstance(obj, list):
                        return [clean_for_json(item) for item in obj]
                    elif isinstance(obj, float):
                        if math.isnan(obj) or math.isinf(obj):
                            return None
                        return obj
                    return obj
                
                cleaned_metadata = clean_for_json(base_metadata)
                metadata_json = {
                    "metadata": cleaned_metadata,
                    "id_to_index": base_id_to_index,
                    "index_to_id": {str(k): v for k, v in base_index_to_id.items()}
                }
                
                cursor.execute("""
                    INSERT INTO rag_vector_index (
                        index_name, form_type, index_data, metadata_json, index_size, vector_count
                    ) VALUES (%s, %s, %s, %s::jsonb, %s, %s)
                    ON CONFLICT (index_name, form_type)
                    DO UPDATE SET
                        index_data = EXCLUDED.index_data,
                        metadata_json = EXCLUDED.metadata_json,
                        index_size = EXCLUDED.index_size,
                        vector_count = EXCLUDED.vector_count,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    'base',
                    '',
                    index_data_bytes,
                    json.dumps(metadata_json, allow_nan=False),
                    index_size,
                    vector_count
                ))
                
                # Shard 삭제
                cursor.execute("""
                    DELETE FROM rag_vector_index
                    WHERE index_name = %s
                """, (shard_identifier,))
                
                return True
                
        except Exception as e:
            print(f"⚠️ Shard merge 실패: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _extract_key_order(self, json_data: Dict[str, Any]) -> Dict[str, Any]:
        if not json_data or not isinstance(json_data, dict):
            return {"page_keys": [], "item_keys": []}
        key_order = {
            "page_keys": list(json_data.keys()),
            "item_keys": []
        }
        if "items" in json_data and isinstance(json_data["items"], list) and len(json_data["items"]) > 0:
            first_item = json_data["items"][0]
            if isinstance(first_item, dict):
                key_order["item_keys"] = list(first_item.keys())
        return key_order
    
    def get_key_order_by_form_type(self, form_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if self.metadata:
            # item_keys가 있는 key_order를 우선적으로 찾기
            # doc_id 기준 정렬로 호출마다 동일한 key_order 선택 (DB에서 읽은 뒤 순서가 섞이지 않도록)
            best_key_order = None
            best_source_doc_id = None
            best_source_meta = None
            fallback_key_order = None
            
            for doc_id, data in sorted(self.metadata.items(), key=lambda x: x[0]):
                metadata_info = data.get("metadata", {}) or {}
                if form_type:
                    if metadata_info.get("form_type") == form_type:
                        key_order = data.get("key_order")
                        if key_order:
                            # item_keys가 있는 key_order를 우선 선택
                            item_keys = key_order.get("item_keys", [])
                            if item_keys and len(item_keys) > 0:
                                best_key_order = key_order
                                best_source_doc_id = doc_id
                                best_source_meta = metadata_info
                                break  # item_keys가 있는 것을 찾으면 즉시 반환
                            elif fallback_key_order is None:
                                fallback_key_order = key_order
                else:
                    key_order = data.get("key_order")
                    if key_order:
                        item_keys = key_order.get("item_keys", [])
                        if item_keys and len(item_keys) > 0:
                            best_key_order = key_order
                            best_source_doc_id = doc_id
                            best_source_meta = metadata_info
                            break
                        elif fallback_key_order is None:
                            fallback_key_order = key_order
            
            # item_keys가 있는 key_order를 우선 반환
            if best_key_order:
                io = best_key_order.get("item_keys", [])
                pdf_name = (best_source_meta or {}).get("pdf_name") or "(메타 없음)"
                page_num = (best_source_meta or {}).get("page_num")
                page_info = f" page={page_num}" if page_num is not None else ""
                print(f"[RAG get_key_order_by_form_type] form_type={form_type} 소스=metadata")
                print(f"  -> key_order 출처: doc_id={best_source_doc_id} pdf_name={pdf_name}{page_info}")
                print(f"  -> item_keys 개수={len(io)} 순서={io[:15]}{'...' if len(io) > 15 else ''}")
                return best_key_order
            
            # 없으면 fallback 반환
            if fallback_key_order:
                return fallback_key_order
        if self.use_db and form_type:
            try:
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    # 단일 글로벌 인덱스만 사용: base (form_type NULL) 또는 shard_*
                    for index_name_pattern in ['base', 'shard_%']:
                        if index_name_pattern == 'base':
                            cursor.execute("""
                                SELECT metadata_json
                                FROM rag_vector_index
                                WHERE index_name = 'base' AND (form_type IS NULL OR form_type = '')
                                ORDER BY updated_at DESC
                                LIMIT 1
                            """)
                        else:
                            cursor.execute("""
                                SELECT metadata_json
                                FROM rag_vector_index
                                WHERE index_name LIKE %s
                                ORDER BY updated_at DESC
                                LIMIT 1
                            """, (index_name_pattern,))
                        row = cursor.fetchone()
                        if row:
                            metadata_json = row[0]
                            if isinstance(metadata_json, str):
                                import json
                                try:
                                    metadata_json = json.loads(metadata_json)
                                except Exception:
                                    continue
                            if isinstance(metadata_json, dict):
                                metadata_dict = metadata_json.get('metadata', {})
                                if not metadata_dict:
                                    continue
                                
                                # item_keys가 있는 key_order를 우선적으로 찾기 (doc_id 정렬로 동일 key_order 보장)
                                best_key_order = None
                                best_source_doc_id = None
                                best_source_meta = None
                                fallback_key_order = None
                                
                                for doc_id, data in sorted(metadata_dict.items(), key=lambda x: x[0]):
                                    if not isinstance(data, dict):
                                        continue
                                    metadata_info = data.get("metadata", {}) or {}
                                    if isinstance(metadata_info, dict):
                                        actual_form_type = metadata_info.get("form_type")
                                        if (actual_form_type == form_type or 
                                            str(actual_form_type) == str(form_type) or
                                            (isinstance(actual_form_type, int) and str(actual_form_type).zfill(2) == form_type) or
                                            (isinstance(form_type, str) and actual_form_type == form_type.zfill(2) if isinstance(actual_form_type, int) else False)):
                                            key_order = data.get("key_order")
                                            if key_order:
                                                # item_keys가 있는 key_order를 우선 선택
                                                item_keys = key_order.get("item_keys", [])
                                                if item_keys and len(item_keys) > 0:
                                                    best_key_order = key_order
                                                    best_source_doc_id = doc_id
                                                    best_source_meta = metadata_info
                                                    break  # item_keys가 있는 것을 찾으면 즉시 반환
                                                elif fallback_key_order is None:
                                                    fallback_key_order = key_order
                                
                                # item_keys가 있는 key_order를 우선 반환
                                if best_key_order:
                                    ko = best_key_order.get("item_keys", [])
                                    pdf_name = (best_source_meta or {}).get("pdf_name") or "(메타 없음)"
                                    page_num = (best_source_meta or {}).get("page_num")
                                    page_info = f" page={page_num}" if page_num is not None else ""
                                    print(f"[RAG get_key_order_by_form_type] form_type={form_type} 소스=DB")
                                    print(f"  -> key_order 출처: doc_id={best_source_doc_id} pdf_name={pdf_name}{page_info}")
                                    print(f"  -> item_keys 개수={len(ko)} 순서={ko[:15]}{'...' if len(ko) > 15 else ''}")
                                    return best_key_order
                                
                                # 없으면 fallback 반환
                                if fallback_key_order:
                                    return fallback_key_order
                                
                                # form_type 매칭이 안되면 item_keys가 있는 첫 번째 key_order 찾기 (doc_id 정렬)
                                for doc_id, data in sorted(metadata_dict.items(), key=lambda x: x[0]):
                                    if not isinstance(data, dict):
                                        continue
                                    key_order = data.get("key_order")
                                    if key_order:
                                        item_keys = key_order.get("item_keys", [])
                                        if item_keys and len(item_keys) > 0:
                                            meta = data.get("metadata", {}) or {}
                                            pdf_name = meta.get("pdf_name") or "(메타 없음)"
                                            page_num = meta.get("page_num")
                                            page_info = f" page={page_num}" if page_num is not None else ""
                                            print(f"[RAG get_key_order_by_form_type] form_type={form_type} 소스=DB(fallback)")
                                            print(f"  -> key_order 출처: doc_id={doc_id} pdf_name={pdf_name}{page_info}")
                                            return key_order
                                        elif fallback_key_order is None:
                                            fallback_key_order = key_order
                                
                                # 최종적으로 fallback 반환
                                if fallback_key_order:
                                    return fallback_key_order
            except Exception as e:
                print(f"  ⚠️ [키 순서 조회] DB 조회 실패: {e}")
                import traceback
                print(f"  상세: {traceback.format_exc()}")
        return None
    
    def get_all_examples(self) -> List[Dict[str, Any]]:
        examples = []
        for doc_id, data in self.metadata.items():
            examples.append({
                "id": doc_id,
                "ocr_text": data.get("ocr_text", ""),
                "answer_json": data.get("answer_json", {}),
                "metadata": data.get("metadata", {}),
                "key_order": data.get("key_order")
            })
        return examples
    
    def count_examples(self) -> int:
        if self.use_db:
            try:
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT vector_count
                        FROM rag_vector_index
                        WHERE index_name = 'base' AND (form_type IS NULL OR form_type = '')
                        ORDER BY updated_at DESC
                        LIMIT 1
                    """)
                    row = cursor.fetchone()
                    if row and row[0]:
                        return row[0]
                    cursor.execute("""
                        SELECT COALESCE(SUM(vector_count), 0)
                        FROM rag_vector_index
                    """)
                    row = cursor.fetchone()
                    if row and row[0]:
                        return row[0]
                    return len(self.metadata)
            except Exception as e:
                print(f"⚠️ DB에서 벡터 수 확인 실패: {e}")
                return len(self.metadata)
        else:
            return len(self.metadata)
    
    @staticmethod
    def preprocess_ocr_text(ocr_text: str) -> str:
        import re
        text = re.sub(r'\s+', ' ', ocr_text)
        text = re.sub(r'(\d+),(\d+)', r'\1\2', text)
        text = re.sub(r'\n+', ' ', text)
        return text.strip()
    
    @staticmethod
    def _tokenize(text: str) -> List[str]:
        import re
        tokens = re.findall(r'\b\w+\b|[가-힣]+|[ひらがなカタカナ]+|[一-龠]+', text)
        return tokens
    
    def _build_bm25_index(self):
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            self._bm25_index = None
            return
        if self._bm25_index is not None:
            return
        all_examples = self.get_all_examples()
        if not all_examples:
            self._bm25_index = None
            return
        self._bm25_texts = []
        self._bm25_example_map = {}
        for example in all_examples:
            ocr_text = example.get("ocr_text", "")
            doc_id = example.get("id", "")
            if not doc_id:
                continue
            preprocessed = self.preprocess_ocr_text(ocr_text)
            tokens = self._tokenize(preprocessed)
            if tokens:
                self._bm25_texts.append(tokens)
                self._bm25_example_map[doc_id] = len(self._bm25_texts) - 1
        if self._bm25_texts:
            self._bm25_index = BM25Okapi(self._bm25_texts)
        else:
            self._bm25_index = None
    
    def _refresh_bm25_index(self):
        self._bm25_index = None
        self._bm25_texts = None
        self._bm25_example_map = None
        self._build_bm25_index()
    
    def _create_search_result(
        self,
        doc_id: str,
        data: Dict[str, Any],
        similarity: float,
        distance: float,
        source: str
    ) -> Dict[str, Any]:
        return {
            "ocr_text": data.get("ocr_text", ""),
            "answer_json": data.get("answer_json", {}),
            "metadata": data.get("metadata", {}),
            "key_order": data.get("key_order"),
            "similarity": similarity,
            "distance": float(distance),
            "id": doc_id,
            "source": source
        }
    
    def _normalize_score(self, score: float, min_score: float, max_score: float) -> float:
        if max_score > min_score:
            return (score - min_score) / (max_score - min_score)
        elif max_score == min_score and max_score > 0:
            return 1.0
        else:
            return 0.0
    
    def search_vector_only(
        self,
        query_text: str,
        top_k: int = 3,
        similarity_threshold: float = 0.7,
        form_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        processed_query = self.preprocess_ocr_text(query_text)
        model = self._get_embedding_model()
        query_embedding = model.encode([processed_query], convert_to_numpy=True).astype('float32')
        all_results = []
        # 단일 글로벌 인덱스만 사용 (form_type 무시)
        index = self.index
        metadata = self.metadata
        id_to_index = self.id_to_index
        index_to_id = self.index_to_id
        if index is None:
            print(f"⚠️ RAG 검색: 인덱스가 None입니다. 벡터 DB가 제대로 로드되지 않았을 수 있습니다.")
            return []
        if index.ntotal > 0:
            k = min(top_k * 2, index.ntotal)
            distances, indices = index.search(query_embedding, k)
            for i, (distance, idx) in enumerate(zip(distances[0], indices[0])):
                if idx == -1:
                    continue
                doc_id = index_to_id.get(idx)
                if not doc_id:
                    continue
                similarity = max(0.0, 1.0 - (distance / 100.0))
                if similarity < similarity_threshold:
                    continue
                data = metadata.get(doc_id, {})
                page_metadata = data.get("metadata", {})
                if page_metadata.get("status") == "deleted":
                    continue
                all_results.append(self._create_search_result(doc_id, data, similarity, distance, "base"))
        else:
            pass
            print(f"⚠️ RAG 검색: 인덱스가 비어있습니다. (ntotal={index.ntotal}, 메타데이터={len(metadata)}개)")
        
        # 유사도로 정렬 및 중복 제거 (doc_id 기준)
        seen_doc_ids = set()
        unique_results = []
        for result in sorted(all_results, key=lambda x: x["similarity"], reverse=True):
            doc_id = result["id"]
            if doc_id not in seen_doc_ids:
                seen_doc_ids.add(doc_id)
                unique_results.append(result)
        
        return unique_results[:top_k]
    
    def search_hybrid(
        self,
        query_text: str,
        top_k: int = 3,
        similarity_threshold: float = 0.7,
        hybrid_alpha: float = 0.5,
        form_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        하이브리드 검색: BM25 + 벡터 검색 결합
        
        Args:
            query_text: 검색 쿼리 텍스트 (OCR 텍스트)
            top_k: 반환할 최대 결과 수
            similarity_threshold: 최소 유사도 임계값 (0.0 ~ 1.0)
            hybrid_alpha: 하이브리드 가중치 (0.0~1.0, 0.5 = 벡터와 BM25 동일 가중치)
            form_type: 양식지 번호 (01, 02, 03, 04, 05). None이면 모든 양식지 (하위 호환성)
            
        Returns:
            검색 결과 리스트 (hybrid_score 포함)
        """
        # BM25 인덱스 구축 (form_type별로 필터링 필요하지만, 현재는 전체 인덱스 사용)
        # TODO: form_type별 BM25 인덱스 구축
        self._build_bm25_index()
        
        if self._bm25_index is None:
            # BM25가 사용 불가능하면 벡터 검색만 사용
            return self.search_vector_only(query_text, top_k, similarity_threshold, form_type)
        
        # 벡터 검색 (더 많은 후보)
        vector_results = self.search_vector_only(
            query_text, top_k * 3, 0.0, form_type  # threshold 무시
        )
        
        # BM25 검색
        processed_query = self.preprocess_ocr_text(query_text)
        query_tokens = self._tokenize(processed_query)
        
        if not query_tokens:
            return self.search_vector_only(query_text, top_k, similarity_threshold, form_type)
        
        bm25_scores_list = self._bm25_index.get_scores(query_tokens)
        
        # doc_id -> BM25 점수 매핑
        bm25_scores = {}
        for doc_id, bm25_idx in self._bm25_example_map.items():
            if bm25_idx < len(bm25_scores_list):
                bm25_scores[doc_id] = bm25_scores_list[bm25_idx]
        
        # 하이브리드 점수 계산
        hybrid_results = []
        candidate_bm25_scores = [bm25_scores.get(r["id"], 0.0) for r in vector_results]
        
        if candidate_bm25_scores:
            max_bm25 = max(candidate_bm25_scores)
            min_bm25 = min(candidate_bm25_scores)
        else:
            max_bm25 = 1.0
            min_bm25 = 0.0
        
        for result in vector_results:
            doc_id = result["id"]
            vector_similarity = result["similarity"]
            
            # BM25 점수 정규화
            bm25_score = bm25_scores.get(doc_id, 0.0)
            normalized_bm25 = self._normalize_score(bm25_score, min_bm25, max_bm25)
            
            # 하이브리드 점수
            hybrid_score = hybrid_alpha * vector_similarity + (1 - hybrid_alpha) * normalized_bm25
            
            # 벡터 유사도가 threshold를 통과하면 하이브리드 점수와 관계없이 포함
            # (BM25 점수가 낮아도 벡터 유사도가 높으면 유지)
            if hybrid_score < similarity_threshold and vector_similarity < similarity_threshold:
                continue
            
            result["bm25_score"] = normalized_bm25
            result["hybrid_score"] = hybrid_score
            hybrid_results.append(result)
        
        # 하이브리드 점수로 정렬
        hybrid_results.sort(key=lambda x: x["hybrid_score"], reverse=True)
        
        return hybrid_results[:top_k]
    
    def search_similar_advanced(
        self,
        query_text: str,
        top_k: int = 3,
        similarity_threshold: float = 0.7,
        search_method: str = "vector",  # "vector", "hybrid"
        hybrid_alpha: float = 0.5,
        form_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        통합 검색 함수 (검색 방식 선택 가능)
        
        Args:
            query_text: 검색 쿼리 텍스트 (OCR 텍스트)
            top_k: 반환할 최대 결과 수
            similarity_threshold: 최소 유사도 임계값 (0.0 ~ 1.0)
            search_method: 검색 방식 ("vector", "hybrid")
            hybrid_alpha: 하이브리드 가중치 (hybrid 방식 사용 시)
            form_type: 양식지 번호 (01, 02, 03, 04, 05). None이면 모든 양식지 (하위 호환성)
            
        Returns:
            검색 결과 리스트
        """
        if search_method == "hybrid":
            return self.search_hybrid(
                query_text, top_k, similarity_threshold, hybrid_alpha, form_type
            )
        else:  # "vector" 또는 기본값
            return self.search_vector_only(
                query_text, top_k, similarity_threshold, form_type
            )


# 전역 RAG Manager 인스턴스 (싱글톤 패턴)
_rag_manager: Optional[RAGManager] = None
_rag_manager_lock = Lock()  # 싱글톤 생성 락


def get_rag_manager(use_db: bool = True) -> RAGManager:
    """
    전역 RAG Manager 인스턴스 반환 (스레드 안전)
    
    Args:
        use_db: True면 DB에 저장, False면 로컬 파일에 저장 (기본값: True)
    
    Returns:
        RAGManager 인스턴스
    """
    global _rag_manager
    if _rag_manager is None:
        with _rag_manager_lock:
            # 이중 체크
            if _rag_manager is None:
                _rag_manager = RAGManager(use_db=use_db)
    return _rag_manager


