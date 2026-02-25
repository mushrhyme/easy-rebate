"""
RAG / 벡터 DB 관리용 관리자 API
"""
import asyncio
import csv
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import json

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from psycopg2.extras import RealDictCursor

from database.registry import get_db
from backend.core.auth import get_current_user
from modules.core.build_faiss_db import build_faiss_db
from modules.core.rag_manager import get_rag_manager
from modules.utils.hash_utils import compute_page_hash, get_page_key
from modules.utils.config import get_project_root


router = APIRouter()


def _ensure_rag_candidate_column(db):
    """
    is_rag_candidate 컬럼이 없으면 추가 (마이그레이션)
    """
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            # 컬럼 존재 여부 확인
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'page_data_current' 
                AND column_name = 'is_rag_candidate'
            """)
            if cursor.fetchone():
                # 컬럼이 이미 존재
                return
            
            # 컬럼이 없으면 추가
            cursor.execute("""
                ALTER TABLE page_data_current
                ADD COLUMN IF NOT EXISTS is_rag_candidate BOOLEAN NOT NULL DEFAULT FALSE
            """)
            cursor.execute("""
                ALTER TABLE page_data_archive
                ADD COLUMN IF NOT EXISTS is_rag_candidate BOOLEAN NOT NULL DEFAULT FALSE
            """)
            conn.commit()
    except Exception as e:
        # 마이그레이션 실패해도 계속 진행 (이미 컬럼이 있을 수도 있음)
        pass


def _ensure_admin(user: Dict[str, Any]) -> None:
    """
    관리자 권한 확인 (username='admin' 또는 is_admin=True)
    """
    if user.get("username") != "admin" and not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="관리자만 접근할 수 있습니다")


def _extract_ocr_for_page(db, pdf_filename: str, page_number: int) -> str:
    """
    페이지 이미지에서 실제 OCR 텍스트 추출 (임베딩용).
    우선순위: DB 저장분(_ocr_text) → debug2 → 이미지 Azure(표 복원) → PDF → result
    """
    pdf_name = pdf_filename[:-4] if pdf_filename.lower().endswith(".pdf") else pdf_filename
    ocr_text = ""

    # 0) 保存時に画面から送ったOCR（再抽出しない）
    try:
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT page_meta FROM page_data_current WHERE pdf_filename = %s AND page_number = %s",
                (pdf_filename, page_number),
            )
            row = cur.fetchone()
            if row and row[0]:
                meta = row[0] if isinstance(row[0], dict) else (json.loads(row[0]) if isinstance(row[0], str) else None)
                if isinstance(meta, dict) and meta.get("_ocr_text"):
                    return (meta["_ocr_text"] or "").strip()
    except Exception:
        pass

    # 1) debug2 파일
    try:
        root = get_project_root()
        debug2_file = root / "debug2" / pdf_name / f"page_{page_number}_ocr_text.txt"
        if debug2_file.exists():
            ocr_text = debug2_file.read_text(encoding="utf-8").strip()
    except Exception:
        pass

    # 2) 저장된 페이지 이미지로 Azure OCR + 표 복원
    if not ocr_text.strip():
        try:
            image_path = db.get_page_image_path(pdf_filename, page_number)
            if image_path:
                root = get_project_root()
                full_path = Path(image_path) if Path(image_path).is_absolute() else root / image_path
                if full_path.exists():
                    from modules.core.extractors.azure_extractor import get_azure_extractor
                    from modules.utils.table_ocr_utils import raw_to_table_restored_text
                    extractor = get_azure_extractor(model_id="prebuilt-layout", enable_cache=False)
                    raw = extractor.extract_from_image_raw(image_path=full_path)
                    if raw:
                        ocr_text = raw_to_table_restored_text(raw)
        except Exception:
            pass

    # 3) PDF 파일에서 Azure(표 복원) 또는 PyMuPDF 폴백
    if not ocr_text.strip():
        try:
            from modules.utils.pdf_utils import find_pdf_path, PdfTextExtractor
            pdf_path_str = find_pdf_path(pdf_name)
            if pdf_path_str:
                extractor = PdfTextExtractor(upload_channel="mail")
                ocr_text = extractor.extract_text(Path(pdf_path_str), page_number) or ""
                extractor.close_all()
        except Exception:
            pass

    # 4) result/ 페이지 JSON의 text 필드
    if not ocr_text.strip():
        try:
            from modules.core.storage import PageStorage
            page_data = PageStorage.load_page(pdf_name, page_number)
            if page_data and isinstance(page_data.get("text"), str):
                ocr_text = page_data["text"]
        except Exception:
            pass

    return ocr_text.strip()


@router.post("/build")
async def build_vector_db(
    payload: Dict[str, Optional[str]] = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    벡터 DB 재구축 트리거 (관리자 전용)

    - 선택적으로 form_type(예: '01', '02') 를 지정할 수 있음
      지정하지 않으면 모든 양식 폴더 대상
    - 현재는 img 폴더 기반 build_faiss_db 를 그대로 사용
    """
    _ensure_admin(current_user)

    form_type: Optional[str] = None
    if payload:
        form_type = payload.get("form_type") or None

    # 스레드 풀에서 실행하여 이벤트 루프 블로킹 방지
    logger.info("ベクターDB再構築 開始 (img フォルダ走査)")
    try:
        await asyncio.to_thread(
            build_faiss_db,
            form_folder=form_type,
            auto_merge=True,
            text_extraction_method="excel",
        )
        logger.info("ベクターDB再構築 完了")
    except Exception as e:
        logger.exception("ベクターDB再構築 エラー")
        raise HTTPException(status_code=500, detail=f"벡터 DB 생성 중 오류가 발생했습니다: {e}")

    # 최신 통계 조회
    rag_manager = get_rag_manager()
    total_vectors = rag_manager.count_examples()

    db = get_db()
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT form_type, SUM(vector_count) AS total_vectors
            FROM rag_vector_index
            GROUP BY form_type
            ORDER BY form_type
            """
        )
        per_form = [
            {"form_type": row[0], "vector_count": int(row[1] or 0)}
            for row in cursor.fetchall()
        ]

    return {
        "success": True,
        "message": "벡터 DB 생성이 완료되었습니다.",
        "total_vectors": int(total_vectors),
        "per_form_type": per_form,
    }


@router.get("/status")
async def get_vector_db_status(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    현재 벡터 DB 상태 조회. 로그인 사용자 전체 허용 (읽기 전용).
    answer_key_pages_*: 사용자가 정답지로 지정해 DB에 올라간 문서의 페이지 수 (Img 폴더 제외).
    """
    # 읽기 전용이므로 관리자 제한 없음 — 현황 탭에서 비관리자도 RAG·文書様式·ページ役割 확인 가능
    rag_manager = get_rag_manager()
    total_vectors = rag_manager.count_examples()

    db = get_db()
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT form_type, SUM(vector_count) AS total_vectors
            FROM rag_vector_index
            GROUP BY form_type
            ORDER BY form_type
            """
        )
        per_form = [
            {"form_type": row[0], "vector_count": int(row[1] or 0)}
            for row in cursor.fetchall()
        ]

        # 정답지 문서(DB) 페이지 수: 전체 / 이번달 / 지난달 (created_at 기준)
        cursor.execute(
            """
            SELECT COALESCE(SUM(total_pages), 0) FROM (
                SELECT total_pages FROM documents_current WHERE is_answer_key_document = TRUE
                UNION ALL
                SELECT total_pages FROM documents_archive WHERE is_answer_key_document = TRUE
            ) t
            """
        )
        answer_key_pages_total = int(cursor.fetchone()[0] or 0)

        cursor.execute(
            """
            SELECT COALESCE(SUM(total_pages), 0) FROM (
                SELECT total_pages FROM documents_current
                WHERE is_answer_key_document = TRUE AND created_at >= date_trunc('month', CURRENT_DATE)
                UNION ALL
                SELECT total_pages FROM documents_archive
                WHERE is_answer_key_document = TRUE AND created_at >= date_trunc('month', CURRENT_DATE)
            ) t
            """
        )
        answer_key_pages_this_month = int(cursor.fetchone()[0] or 0)

        cursor.execute(
            """
            SELECT COALESCE(SUM(total_pages), 0) FROM (
                SELECT total_pages FROM documents_current
                WHERE is_answer_key_document = TRUE
                  AND created_at >= date_trunc('month', CURRENT_DATE) - interval '1 month'
                  AND created_at < date_trunc('month', CURRENT_DATE)
                UNION ALL
                SELECT total_pages FROM documents_archive
                WHERE is_answer_key_document = TRUE
                  AND created_at >= date_trunc('month', CURRENT_DATE) - interval '1 month'
                  AND created_at < date_trunc('month', CURRENT_DATE)
            ) t
            """
        )
        answer_key_pages_last_month = int(cursor.fetchone()[0] or 0)

    return {
        "total_vectors": int(total_vectors),
        "per_form_type": per_form,
        "answer_key_pages_total": answer_key_pages_total,
        "answer_key_pages_this_month": answer_key_pages_this_month,
        "answer_key_pages_last_month": answer_key_pages_last_month,
    }


class BuildFromLearningPagesRequest(BaseModel):
    """검토 화면에서 선택한 페이지들로 벡터 DB 생성 요청"""

    form_type: Optional[str] = None


@router.get("/learning-flag")
async def get_learning_flag(
    pdf_filename: str,
    page_number: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    특정 페이지가 벡터 DB 학습 대상인지 여부 조회 (관리자 전용)
    """
    _ensure_admin(current_user)

    db = get_db()
    _ensure_rag_candidate_column(db)  # 컬럼이 없으면 자동 추가
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT is_rag_candidate
            FROM page_data_current
            WHERE pdf_filename = %s AND page_number = %s
            """,
            (pdf_filename, page_number),
        )
        row = cursor.fetchone()

    return {"selected": bool(row[0]) if row else False}


class LearningFlagRequest(BaseModel):
    pdf_filename: str
    page_number: int
    selected: bool


@router.post("/learning-flag")
async def set_learning_flag(
    request: LearningFlagRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    특정 페이지의 벡터 DB 학습 대상 플래그 설정 (관리자 전용)
    """
    _ensure_admin(current_user)

    db = get_db()
    _ensure_rag_candidate_column(db)  # 컬럼이 없으면 자동 추가
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE page_data_current
            SET is_rag_candidate = %s, updated_at = CURRENT_TIMESTAMP
            WHERE pdf_filename = %s AND page_number = %s
            """,
            (request.selected, request.pdf_filename, request.page_number),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Page not found")

    return {"success": True}


@router.get("/learning-pages")
async def get_learning_pages(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    현재 벡터 DB 학습 대상으로 체크된 페이지 목록 조회 (관리자 전용)
    """
    _ensure_admin(current_user)

    db = get_db()
    _ensure_rag_candidate_column(db)  # 컬럼이 없으면 자동 추가
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT pdf_filename, page_number
            FROM page_data_current
            WHERE is_rag_candidate = TRUE
            ORDER BY pdf_filename, page_number
            """
        )
        rows = cursor.fetchall()

    pages = [{"pdf_filename": r[0], "page_number": r[1]} for r in rows]
    return {"count": len(pages), "pages": pages}


@router.post("/build-from-learning-pages")
async def build_vector_from_learning_pages(
    request: BuildFromLearningPagesRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    is_rag_candidate = TRUE 로 설정된 페이지들로부터 벡터 DB 생성 (관리자 전용)
    """
    _ensure_admin(current_user)

    db = get_db()
    _ensure_rag_candidate_column(db)  # 컬럼이 없으면 자동 추가
    
    with db.get_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        # LEFT JOIN: items 없는 페이지(cover 전용)도 포함
        cursor.execute(
            """
            SELECT 
                p.pdf_filename,
                p.page_number,
                p.page_role,
                p.page_meta,
                i.item_id,
                i.item_order,
                i.item_data,
                d.form_type,
                d.data_year,
                d.data_month
            FROM page_data_current p
            LEFT JOIN items_current i
              ON i.pdf_filename = p.pdf_filename
             AND i.page_number = p.page_number
            LEFT JOIN documents_current d
              ON p.pdf_filename = d.pdf_filename
            WHERE p.is_rag_candidate = TRUE
            ORDER BY p.pdf_filename, p.page_number, i.item_order NULLS LAST
            """
        )
        rows: List[Dict[str, Any]] = cursor.fetchall()

    if not rows:
        raise HTTPException(status_code=400, detail="학습 대상으로 선택된 페이지가 없습니다.")

    # form_type 결정 (요청값 우선, 없으면 문서에서 첫 번째 값 사용)
    form_type_for_index: Optional[str] = request.form_type
    if not form_type_for_index:
        for row in rows:
            doc_form_type = row.get("form_type")
            if doc_form_type:
                form_type_for_index = doc_form_type
                break
        if not form_type_for_index:
            form_type_for_index = ""

    # (pdf_filename, page_number) 단위로 그룹화 (items 없는 페이지는 1행, item_id=NULL)
    from collections import defaultdict

    pages_map: Dict[Tuple[str, int], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (row["pdf_filename"], row["page_number"])
        pages_map[key].append(row)

    shard_pages: List[Dict[str, Any]] = []

    for (pdf_filename, page_number), item_rows in pages_map.items():
        # pdf_name (확장자 제거)
        pdf_name = pdf_filename[:-4] if pdf_filename.lower().endswith(".pdf") else pdf_filename

        merged_items: List[Dict[str, Any]] = []

        # 연월/폼타입 정보 (첫 행 기준)
        first_row = item_rows[0]
        data_year = first_row.get("data_year")
        data_month = first_row.get("data_month")
        page_role = first_row.get("page_role") or "detail"
        page_meta_raw = first_row.get("page_meta")
        page_meta: Dict[str, Any] = {}
        if page_meta_raw is not None:
            if isinstance(page_meta_raw, dict):
                page_meta = dict(page_meta_raw)
            elif isinstance(page_meta_raw, str):
                try:
                    page_meta = json.loads(page_meta_raw)
                except json.JSONDecodeError:
                    pass

            for row in item_rows:
                if row.get("item_id") is None:
                    # items 없는 페이지(cover): item 행 스킵
                    continue

                item_data = row.get("item_data") or {}
                merged_item = dict(item_data) if isinstance(item_data, dict) else {}
                merged_items.append(merged_item)

        # 실제 OCR 텍스트 추출 (페이지 이미지에서, 임베딩용)
        ocr_text = await asyncio.to_thread(_extract_ocr_for_page, db, pdf_filename, page_number)
        if not ocr_text:
            # OCR 추출 실패 시 스킵 (빈 텍스트로 임베딩할 수 없음)
            continue

        # answer_json: page_meta(문서 메타) + page_role + items
        answer_json: Dict[str, Any] = {
            **page_meta,
            "page_role": page_role,
            "items": merged_items,
        }

        metadata: Dict[str, Any] = {
            "pdf_name": pdf_name,
            "page_num": page_number,
            "form_type": form_type_for_index,
            "source": "db_learning_pages",
            "data_year": data_year,
            "data_month": data_month,
        }

        page_key = get_page_key(pdf_name, page_number)
        page_hash = compute_page_hash(ocr_text, answer_json)

        shard_pages.append(
            {
                "pdf_name": pdf_name,
                "page_num": page_number,
                "ocr_text": ocr_text,
                "answer_json": answer_json,
                "metadata": metadata,
                "page_key": page_key,
                "page_hash": page_hash,
            }
        )

    if not shard_pages:
        raise HTTPException(status_code=400, detail="벡터화할 유효한 데이터가 없습니다.")

    rag_manager = get_rag_manager()

    result = await asyncio.to_thread(
        rag_manager.build_shard,
        shard_pages,
        form_type=form_type_for_index or None,
    )
    if not result:
        raise HTTPException(status_code=500, detail="Shard 생성에 실패했습니다.")

    shard_identifier, _shard_id = result

    merged = await asyncio.to_thread(rag_manager.merge_shard, shard_identifier)
    if not merged:
        raise HTTPException(
            status_code=500,
            detail="Shard를 base 인덱스에 병합하는 데 실패했습니다.",
        )

    await asyncio.to_thread(rag_manager.reload_index)
    total_vectors = rag_manager.count_examples()

    db = get_db()
    # 登録済みを rag_learning_status_current に反映（管理画面で一覧できるように）
    with db.get_connection() as conn:
        cursor = conn.cursor()
        for sp in shard_pages:
            pdf_name = (sp.get("metadata") or {}).get("pdf_name") or ""
            page_num = (sp.get("metadata") or {}).get("page_num")
            page_hash_val = sp.get("page_hash") or ""
            if not pdf_name or page_num is None:
                continue
            pdf_filename = pdf_name if pdf_name.lower().endswith(".pdf") else f"{pdf_name}.pdf"
            cursor.execute(
                """
                INSERT INTO rag_learning_status_current (
                    pdf_filename, page_number, status, page_hash, shard_id
                ) VALUES (%s, %s, 'merged', %s, %s)
                ON CONFLICT (pdf_filename, page_number)
                DO UPDATE SET
                    status = 'merged',
                    page_hash = EXCLUDED.page_hash,
                    shard_id = EXCLUDED.shard_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (pdf_filename, page_num, page_hash_val, shard_identifier),
            )
        conn.commit()

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT form_type, SUM(vector_count) AS total_vectors
            FROM rag_vector_index
            GROUP BY form_type
            ORDER BY form_type
            """
        )
        per_form = [
            {"form_type": row[0], "vector_count": int(row[1] or 0)}
            for row in cursor.fetchall()
        ]

    return {
        "success": True,
        "message": "선택된 페이지들로부터 벡터 DB를 생성했습니다.",
        "processed_pages": len(shard_pages),
        "total_vectors": int(total_vectors),
        "per_form_type": per_form,
    }


RETAIL_USER_CSV_PATH = get_project_root() / "database" / "csv" / "retail_user.csv"


@router.get("/retail-user-csv")
async def get_retail_user_csv(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """retail_user.csv をそのまま読み、一覧を返す（管理者専用）。担当・スーパータブで CSV 内容を表示。"""
    _ensure_admin(current_user)
    rows: List[Dict[str, str]] = []
    if not RETAIL_USER_CSV_PATH.exists():
        return {"rows": rows}
    try:
        with open(RETAIL_USER_CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append({
                    "super_code": (row.get("대표슈퍼코드") or "").strip(),
                    "super_name": (row.get("대표슈퍼명") or "").strip(),
                    "person_id": (row.get("담당자ID") or "").strip(),
                    "person_name": (row.get("담당자명") or "").strip(),
                    "username": (row.get("ID") or "").strip(),
                })
    except Exception as e:
        logger.exception("retail_user.csv read failed: %s", e)
        raise HTTPException(status_code=500, detail="CSVの読み込みに失敗しました")
    return {"rows": rows}


class RetailUserCsvPutBody(BaseModel):
    """retail_user.csv 全体を上書きする用。"""
    rows: List[Dict[str, str]]


@router.put("/retail-user-csv")
async def put_retail_user_csv(
    body: RetailUserCsvPutBody,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """retail_user.csv を指定内容で上書き（管理者専用）。"""
    _ensure_admin(current_user)
    try:
        with open(RETAIL_USER_CSV_PATH, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["대표슈퍼코드", "대표슈퍼명", "담당자ID", "담당자명", "ID"])
            for r in body.rows:
                writer.writerow([
                    (r.get("super_code") or "").strip(),
                    (r.get("super_name") or "").strip(),
                    (r.get("person_id") or "").strip(),
                    (r.get("person_name") or "").strip(),
                    (r.get("username") or "").strip(),
                ])
    except Exception as e:
        logger.exception("retail_user.csv write failed: %s", e)
        raise HTTPException(status_code=500, detail="CSVの書き込みに失敗しました")
    return {"message": "保存しました", "rows_count": len(body.rows)}


DIST_RETAIL_CSV_PATH = get_project_root() / "database" / "csv" / "dist_retail.csv"


@router.get("/dist-retail-csv")
async def get_dist_retail_csv(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """dist_retail.csv をそのまま読み、一覧を返す（管理者専用）。"""
    _ensure_admin(current_user)
    rows: List[Dict[str, str]] = []
    if not DIST_RETAIL_CSV_PATH.exists():
        return {"rows": rows}
    try:
        with open(DIST_RETAIL_CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append({
                    "dist_code": (row.get("판매처코드") or "").strip(),
                    "dist_name": (row.get("판매처명") or "").strip(),
                    "super_code": (row.get("대표슈퍼코드") or "").strip(),
                    "super_name": (row.get("대표슈퍼명") or "").strip(),
                    "person_id": (row.get("담당자ID") or "").strip(),
                    "person_name": (row.get("담당자명") or "").strip(),
                })
    except Exception as e:
        logger.exception("dist_retail.csv read failed: %s", e)
        raise HTTPException(status_code=500, detail="CSVの読み込みに失敗しました")
    return {"rows": rows}


class DistRetailCsvPutBody(BaseModel):
    """dist_retail.csv 全体を上書きする用。"""
    rows: List[Dict[str, str]]


@router.put("/dist-retail-csv")
async def put_dist_retail_csv(
    body: DistRetailCsvPutBody,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """dist_retail.csv を指定内容で上書き（管理者専用）。"""
    _ensure_admin(current_user)
    try:
        with open(DIST_RETAIL_CSV_PATH, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["판매처코드", "판매처명", "대표슈퍼코드", "대표슈퍼명", "담당자ID", "담당자명"])
            for r in body.rows:
                writer.writerow([
                    (r.get("dist_code") or "").strip(),
                    (r.get("dist_name") or "").strip(),
                    (r.get("super_code") or "").strip(),
                    (r.get("super_name") or "").strip(),
                    (r.get("person_id") or "").strip(),
                    (r.get("person_name") or "").strip(),
                ])
    except Exception as e:
        logger.exception("dist_retail.csv write failed: %s", e)
        raise HTTPException(status_code=500, detail="CSVの書き込みに失敗しました")
    return {"message": "保存しました", "rows_count": len(body.rows)}


# ---- 基準管理 (master_code.xlsx) ----
MASTER_CODE_PATH = get_project_root() / "master_code.xlsx"
MASTER_CODE_KEYS = ("a", "b", "c", "d", "e", "f")


def _cell_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _read_master_code_xlsx() -> Tuple[List[str], List[Dict[str, str]]]:
    """master_code.xlsx を読み、1行目をヘッダー、2行目以降を rows (a,b,c,d,e,f) で返す。"""
    headers = ["取引先コード", "取引先名称", "代表スーパーコード", "代表スーパー名称", "担当ID", "担当者"]
    rows: List[Dict[str, str]] = []
    if not MASTER_CODE_PATH.exists():
        return headers, rows
    try:
        import openpyxl
        wb = openpyxl.load_workbook(MASTER_CODE_PATH, read_only=True)
        ws = wb.active
        all_rows = list(ws.iter_rows(min_row=1, max_col=6, values_only=True))
        wb.close()
        if not all_rows:
            return headers, rows
        first = all_rows[0]
        headers = [_cell_str(first[i]) if i < len(first) else "" for i in range(6)]
        for row in all_rows[1:]:
            a = _cell_str(row[0]) if len(row) > 0 else ""
            b = _cell_str(row[1]) if len(row) > 1 else ""
            c = _cell_str(row[2]) if len(row) > 2 else ""
            d = _cell_str(row[3]) if len(row) > 3 else ""
            e = _cell_str(row[4]) if len(row) > 4 else ""
            f = _cell_str(row[5]) if len(row) > 5 else ""
            rows.append({"a": a, "b": b, "c": c, "d": d, "e": e, "f": f})
    except Exception:
        pass
    return headers, rows


class MasterCodeSaveRequest(BaseModel):
    headers: Optional[List[str]] = None
    rows: List[Dict[str, str]]


@router.get("/master-code")
async def get_master_code(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """master_code.xlsx を読み、ヘッダーと全行を返す（管理者専用）。"""
    _ensure_admin(current_user)
    headers, rows = _read_master_code_xlsx()
    return {"headers": headers, "rows": rows}


@router.put("/master-code")
async def save_master_code(
    request: MasterCodeSaveRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """master_code.xlsx に rows を書き戻す（管理者専用）。"""
    _ensure_admin(current_user)
    headers, _ = _read_master_code_xlsx()
    if request.headers and len(request.headers) >= 6:
        headers = [str(h) for h in request.headers[:6]]
    try:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(headers)
        for r in request.rows:
            row = [r.get(k, "") for k in MASTER_CODE_KEYS]
            ws.append(row)
        wb.save(MASTER_CODE_PATH)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存に失敗しました: {e}")
    return {"success": True, "message": "保存しました。"}

