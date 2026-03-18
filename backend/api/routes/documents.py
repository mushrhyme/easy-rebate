"""
문서 업로드 및 관리 API
"""
import asyncio
import base64
import json
import logging
import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from io import BytesIO
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, Depends
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel

from database.registry import get_db
from database.table_selector import get_table_name, get_table_suffix
from modules.core.processor import PdfProcessor
from modules.utils.config import rag_config, get_project_root
from modules.utils.retail_resolve import resolve_retail_dist
from modules.utils.finet01_cs_utils import apply_finet01_cs_irisu
from modules.utils.form04_mishu_utils import apply_form04_mishu_decimal
from backend.unit_price_lookup import resolve_product_and_prices
from backend.core.session import SessionManager

# 분석 완료 이미지: static/images/{pdf_filename}/ 하위에 저장됨. DB 삭제 시 함께 삭제.
def _delete_static_images_for_document(pdf_filename: str) -> None:
    """문서(pdf_filename)에 해당하는 static 이미지 디렉터리 삭제."""
    root = get_project_root()
    img_dir = root / "static" / "images" / pdf_filename
    if img_dir.exists() and img_dir.is_dir():
        shutil.rmtree(img_dir, ignore_errors=True)


def _delete_debug2_for_document(pdf_filename: str) -> None:
    """문서(pdf_filename)에 해당하는 debug2 디렉터리 삭제 (RAG/LLM 디버그 출력 등)."""
    root = get_project_root()
    debug_dir = root / "debug2" / pdf_filename
    if debug_dir.exists() and debug_dir.is_dir():
        shutil.rmtree(debug_dir, ignore_errors=True)
from backend.core.config import settings
from backend.core.auth import get_current_user, get_current_user_id
from backend.core.activity_log import log as activity_log
from backend.api.routes.websocket import manager

# 사용자별 동시 PDF 분석: 1인당 1건 (env: MAX_CONCURRENT_ANALYSES_PER_USER)
# 전역 상한: 동시 분석 총개수 (env: MAX_CONCURRENT_ANALYSES) — 한 사용자가 슬롯을 다 쓰지 않도록
_MAX_PER_USER = int(os.getenv("MAX_CONCURRENT_ANALYSES_PER_USER", "1"))
_MAX_GLOBAL = int(os.getenv("MAX_CONCURRENT_ANALYSES", "20"))
_user_analysis_semaphores: dict[int, asyncio.Semaphore] = {}
_user_semaphore_lock = asyncio.Lock()
_global_analysis_semaphore = asyncio.Semaphore(_MAX_GLOBAL)
# PDF 분석 전용 스레드 풀: run_sync(DB)와 분리해 경합 완화
_analysis_executor = ThreadPoolExecutor(max_workers=min(10, _MAX_GLOBAL), thread_name_prefix="pdf_analysis")
# 이 페이지 이후 전체 재분석 진행 시 학습 요청으로 중단하기 위한 이벤트 (key=pdf_filename)
_reanalysis_cancel_events: dict[str, asyncio.Event] = {}
_reanalysis_lock = asyncio.Lock()


async def _get_user_analysis_semaphore(user_id: int) -> asyncio.Semaphore:
    """사용자별 세마포어(동시 1건). 없으면 생성해 반환."""
    async with _user_semaphore_lock:
        if user_id not in _user_analysis_semaphores:
            _user_analysis_semaphores[user_id] = asyncio.Semaphore(_MAX_PER_USER)
        return _user_analysis_semaphores[user_id]


router = APIRouter()


def _ensure_last_edited_columns(db):
    """last_edited_at, last_edited_by_user_id 컬럼 마이그레이션 (Phase 1)"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'page_data_current' AND column_name = 'last_edited_at'
            """)
            if cursor.fetchone():
                return
            cursor.execute("ALTER TABLE page_data_current ADD COLUMN IF NOT EXISTS last_edited_at TIMESTAMPTZ NULL")
            cursor.execute("ALTER TABLE page_data_current ADD COLUMN IF NOT EXISTS last_edited_by_user_id INTEGER NULL")
            cursor.execute("ALTER TABLE page_data_archive ADD COLUMN IF NOT EXISTS last_edited_at TIMESTAMPTZ NULL")
            cursor.execute("ALTER TABLE page_data_archive ADD COLUMN IF NOT EXISTS last_edited_by_user_id INTEGER NULL")
            conn.commit()
    except Exception:
        pass


def _ensure_answer_key_designated_by_column(db):
    """answer_key_designated_by_user_id が無ければ追加（マイグレーション）"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'documents_current' AND column_name = 'answer_key_designated_by_user_id'
            """)
            if cursor.fetchone():
                return
            cursor.execute("""
                ALTER TABLE documents_current
                ADD COLUMN IF NOT EXISTS answer_key_designated_by_user_id INTEGER REFERENCES users(user_id)
            """)
            cursor.execute("""
                ALTER TABLE documents_archive
                ADD COLUMN IF NOT EXISTS answer_key_designated_by_user_id INTEGER REFERENCES users(user_id)
            """)
            conn.commit()
    except Exception:
        pass


def _ensure_phase1_rag_columns(db):
    """Phase 1: current_vector_version(documents), ocr_text/analyzed_vector_version/last_analyzed_at(page_data) 추가."""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'documents_current' AND column_name = 'current_vector_version'
            """)
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE documents_current ADD COLUMN current_vector_version INTEGER NOT NULL DEFAULT 1")
                cursor.execute("ALTER TABLE documents_archive ADD COLUMN current_vector_version INTEGER NOT NULL DEFAULT 1")
            cursor.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'page_data_current' AND column_name = 'ocr_text'
            """)
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE page_data_current ADD COLUMN ocr_text TEXT")
                cursor.execute("ALTER TABLE page_data_archive ADD COLUMN ocr_text TEXT")
            cursor.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'page_data_current' AND column_name = 'analyzed_vector_version'
            """)
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE page_data_current ADD COLUMN analyzed_vector_version INTEGER")
                cursor.execute("ALTER TABLE page_data_archive ADD COLUMN analyzed_vector_version INTEGER")
            cursor.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'page_data_current' AND column_name = 'last_analyzed_at'
            """)
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE page_data_current ADD COLUMN last_analyzed_at TIMESTAMPTZ")
                cursor.execute("ALTER TABLE page_data_archive ADD COLUMN last_analyzed_at TIMESTAMPTZ")
            conn.commit()
    except Exception:
        pass


def _answer_key_debug_dir(pdf_filename: str) -> Path:
    """정답지 생성 디버깅용: debug/answer_key/{문서명}/ 경로 반환 (폴더는 호출측에서 생성)."""
    stem = Path(pdf_filename).stem
    safe_name = stem.replace("\\", "_").replace("/", "_").strip() or "unknown"
    return get_project_root() / "debug" / "answer_key" / safe_name


def _get_ocr_text_azure_sync(db, pdf_filename: str, page_number: int) -> str:
    """
    해당 페이지의 OCR 텍스트를 Azure(표 복원) 경로로만 추출. 정답 생성 RAG용.
    우선순위: DB(page_meta._ocr_text, ocr_text) → 저장된 이미지 Azure(표 복원) → PDF Azure(표 복원).
    """
    root = get_project_root()
    pdf_name = pdf_filename[:-4] if pdf_filename.lower().endswith(".pdf") else pdf_filename
    ocr_text = ""
    # 0) DB: page_data_current.ocr_text / page_meta._ocr_text
    try:
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT page_meta, ocr_text FROM page_data_current WHERE pdf_filename = %s AND page_number = %s",
                (pdf_filename, page_number),
            )
            row = cur.fetchone()
            if row:
                meta = row[0] if isinstance(row[0], dict) else (json.loads(row[0]) if row[0] and isinstance(row[0], str) else None)
                if isinstance(meta, dict) and (meta.get("_ocr_text") or "").strip():
                    return (meta["_ocr_text"] or "").strip()
                if row[1] and (row[1] or "").strip():
                    return (row[1] or "").strip()
    except Exception:
        pass
    # 1) 저장된 페이지 이미지 → Azure(표 복원)
    if not ocr_text.strip():
        try:
            image_path = db.get_page_image_path(pdf_filename, page_number)
            if image_path:
                full_path = Path(image_path) if Path(image_path).is_absolute() else root / image_path
                if full_path.exists():
                    from modules.core.extractors.azure_extractor import get_azure_extractor
                    from modules.utils.table_ocr_utils import raw_to_table_restored_text
                    extractor = get_azure_extractor(model_id="prebuilt-layout", enable_cache=False)
                    raw = extractor.extract_from_image_raw(image_path=full_path)
                    if raw:
                        ocr_text = raw_to_table_restored_text(raw) or ""
        except Exception:
            pass
    # 2) PDF → Azure(표 복원)
    if not ocr_text.strip():
        try:
            from modules.utils.pdf_utils import find_pdf_path, PdfTextExtractor
            pdf_path_str = find_pdf_path(pdf_name)
            if pdf_path_str:
                ext = PdfTextExtractor(upload_channel="mail")
                try:
                    ocr_text = ext.extract_text(Path(pdf_path_str), page_number) or ""
                finally:
                    ext.close_all()
        except Exception:
            pass
    return (ocr_text or "").strip()


# 업로드/검토 탭: img 폴더 기반 build_faiss_db로만 등록된 문서(created_by_user_id IS NULL) 제외
# 현황 탭: 제외하지 않음 (exclude_img_seed=False)


def query_documents_table(
    db,
    form_type: Optional[str] = None,
    upload_channel: Optional[str] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
    is_answer_key_document: Optional[bool] = None,
    exclude_answer_key: Optional[bool] = None,
    answer_key_designated_by_user_id: Optional[int] = None,
    exclude_img_seed: bool = False,
) -> List[Tuple]:
    """
    documents 테이블 조회 헬퍼 (current/archive 자동 선택).

    Args:
        exclude_img_seed: True면 created_by_user_id IS NULL 문서 제외 (업로드/검토/정답지 탭용).
                          False면 전부 포함 (현황 탭용).
    """
    seed_filter = " AND created_by_user_id IS NOT NULL" if exclude_img_seed else ""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        if is_answer_key_document:
            answer_key_filter = " AND is_answer_key_document = TRUE"
        elif exclude_answer_key:
            answer_key_filter = " AND (COALESCE(is_answer_key_document, FALSE) = FALSE)"
        else:
            answer_key_filter = ""
        designated_filter = " AND answer_key_designated_by_user_id = %s" if (is_answer_key_document and answer_key_designated_by_user_id is not None) else ""

        if year is not None and month is not None:
            table_suffix = get_table_suffix(year, month)
            documents_table = f"documents_{table_suffix}"
            filter_cond = upload_channel or form_type
            if filter_cond:
                col, val = ("upload_channel", upload_channel) if upload_channel else ("form_type", form_type)
                params: tuple = (val,) if not designated_filter else (val, answer_key_designated_by_user_id)
                cursor.execute(f"""
                    SELECT pdf_filename, total_pages, form_type, upload_channel, created_at, data_year, data_month,
                           COALESCE(is_answer_key_document, FALSE)
                    FROM {documents_table}
                    WHERE {col} = %s{answer_key_filter}{designated_filter}{seed_filter}
                    ORDER BY created_at DESC
                """, params)
            else:
                params = () if not designated_filter else (answer_key_designated_by_user_id,)
                cursor.execute(f"""
                    SELECT pdf_filename, total_pages, form_type, upload_channel, created_at, data_year, data_month,
                           COALESCE(is_answer_key_document, FALSE)
                    FROM {documents_table}
                    WHERE 1=1{answer_key_filter}{designated_filter}{seed_filter}
                    ORDER BY created_at DESC
                """, params)
            rows = cursor.fetchall()
        else:
            filter_cond = upload_channel or form_type
            col, val = ("upload_channel", upload_channel) if upload_channel else ("form_type", form_type)
            if filter_cond:
                if designated_filter:
                    params = (val, val, answer_key_designated_by_user_id, answer_key_designated_by_user_id)
                else:
                    params = (val, val)
                cursor.execute(f"""
                    SELECT pdf_filename, total_pages, form_type, upload_channel, created_at, data_year, data_month,
                           COALESCE(is_answer_key_document, FALSE)
                    FROM documents_current
                    WHERE {col} = %s{answer_key_filter}{designated_filter}{seed_filter}
                    UNION ALL
                    SELECT pdf_filename, total_pages, form_type, upload_channel, created_at, data_year, data_month,
                           COALESCE(is_answer_key_document, FALSE)
                    FROM documents_archive
                    WHERE {col} = %s{answer_key_filter}{designated_filter}{seed_filter}
                    ORDER BY created_at DESC
                """, params)
            else:
                if designated_filter:
                    params = (answer_key_designated_by_user_id, answer_key_designated_by_user_id)
                else:
                    params = ()
                cursor.execute(f"""
                    SELECT pdf_filename, total_pages, form_type, upload_channel, created_at, data_year, data_month,
                           COALESCE(is_answer_key_document, FALSE)
                    FROM documents_current
                    WHERE 1=1{answer_key_filter}{designated_filter}{seed_filter}
                    UNION ALL
                    SELECT pdf_filename, total_pages, form_type, upload_channel, created_at, data_year, data_month,
                           COALESCE(is_answer_key_document, FALSE)
                    FROM documents_archive
                    WHERE 1=1{answer_key_filter}{designated_filter}{seed_filter}
                    ORDER BY created_at DESC
                """, params)
            rows = cursor.fetchall()
    return rows


def query_page_meta_batch(
    db,
    pdf_filenames: List[str],
    year: Optional[int] = None,
    month: Optional[int] = None
) -> List[Tuple]:
    """
    page_data 테이블에서 page_meta 배치 조회 헬퍼 함수
    
    Args:
        db: 데이터베이스 인스턴스
        pdf_filenames: PDF 파일명 리스트
        year: 연도 (선택사항, 없으면 current + archive 모두 조회)
        month: 월 (선택사항, 없으면 current + archive 모두 조회)
    
    Returns:
        (pdf_filename, page_meta) 튜플 리스트
    """
    if not pdf_filenames:
        return []
    
    query_start = time.perf_counter()
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # 연월이 지정되면 해당 테이블만 조회
        if year is not None and month is not None:
            table_suffix = get_table_suffix(year, month)
            page_data_table = f"page_data_{table_suffix}"
            cursor.execute(f"""
                SELECT pdf_filename, page_meta
                FROM {page_data_table}
                WHERE pdf_filename = ANY(%s) AND page_number = 1
            """, (pdf_filenames,))
        else:
            # current + archive 모두 조회
            cursor.execute("""
                SELECT pdf_filename, page_meta
                FROM page_data_current
                WHERE pdf_filename = ANY(%s) AND page_number = 1
                UNION ALL
                SELECT pdf_filename, page_meta
                FROM page_data_archive
                WHERE pdf_filename = ANY(%s) AND page_number = 1
            """, (pdf_filenames, pdf_filenames))
        
        page_meta_rows = cursor.fetchall()
    
    return page_meta_rows


def extract_year_month_from_billing_date(billing_date_str: str) -> Optional[Tuple[int, int]]:
    """
    請求年月 문자열에서 연월 추출
    
    Args:
        billing_date_str: "2025年02月" 또는 "2025年02月分" 형식의 문자열
    
    Returns:
        (year, month) 튜플 또는 None
    """
    if not billing_date_str:
        return None
    
    # "2025年02月" 또는 "2025年02月分" 형식 파싱
    # 한자 숫자도 처리: "２０２５年０２月"
    patterns = [
        r'(\d{4})年(\d{1,2})月',  # "2025年02月"
        r'([０-９]{4})年([０-９]{1,2})月',  # "２０２５年０２月" (전각 숫자)
    ]
    
    for pattern in patterns:
        match = re.search(pattern, billing_date_str)
        if match:
            year_str = match.group(1)
            month_str = match.group(2)
            
            # 전각 숫자를 반각으로 변환
            if year_str[0] == '０':
                year_str = year_str.translate(str.maketrans('０１２３４５６７８９', '0123456789'))
                month_str = month_str.translate(str.maketrans('０１２３４５６７８９', '0123456789'))
            
            try:
                year = int(year_str)
                month = int(month_str)
                if 1 <= month <= 12:
                    return (year, month)
            except ValueError:
                continue
    
    return None


def _get_analyzed_page_numbers_sync(db, pdf_filename: str) -> List[int]:
    """문서별 분석 완료된 페이지 번호 목록 (page_data_current 기준)."""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT page_number FROM page_data_current WHERE pdf_filename = %s ORDER BY page_number",
                (pdf_filename,),
            )
            return [row[0] for row in cursor.fetchall()]
    except Exception:
        return []


def get_document_year_month(db, pdf_filename: str, year: Optional[int] = None, month: Optional[int] = None) -> Optional[Tuple[int, int]]:
    """
    문서의 첫 번째 페이지에서 請求年月 추출
    
    Args:
        db: 데이터베이스 인스턴스
        pdf_filename: PDF 파일명
        year: 연도 (선택사항, 테이블 선택용)
        month: 월 (선택사항, 테이블 선택용)
    
    Returns:
        (year, month) 튜플 또는 None
    """
    try:
        # 연월에 따라 테이블 선택
        if year is not None and month is not None:
            table_suffix = get_table_suffix(year, month)
            page_data_table = f"page_data_{table_suffix}"
        else:
            # current에서 먼저 찾고, 없으면 archive에서 찾기
            page_data_table = "page_data_current"
        
        # 첫 번째 페이지의 page_meta 조회
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT page_meta
                FROM {page_data_table}
                WHERE pdf_filename = %s AND page_number = 1
            """, (pdf_filename,))
            row = cursor.fetchone()
            
            if not row or not row[0]:
                return None
            
            # page_meta가 JSON이므로 필요 시 파싱
            page_meta = row[0]
            if isinstance(page_meta, str):
                page_meta = json.loads(page_meta)
            
            # document_meta에서 請求年月 찾기
            document_meta = page_meta.get('document_meta', {})
            if isinstance(document_meta, str):
                document_meta = json.loads(document_meta)
            
            if not isinstance(document_meta, dict):
                # page_meta 자체에서 직접 찾기 시도
                billing_date = page_meta.get('請求年月')
                if billing_date:
                    result = extract_year_month_from_billing_date(billing_date)
                    if result:
                        return result
            else:
                billing_date = document_meta.get('請求年月')
                if billing_date:
                    result = extract_year_month_from_billing_date(billing_date)
                    if result:
                        return result
                
                # 다른 가능한 필드명도 확인
                for key in ['請求年月分', '請求期間', '対象期間']:
                    if key in document_meta:
                        value = document_meta[key]
                        if isinstance(value, str):
                            result = extract_year_month_from_billing_date(value)
                            if result:
                                return result
            
    except Exception:
        pass
    
    return None


class DocumentResponse(BaseModel):
    """문서 응답 모델"""
    pdf_filename: str
    total_pages: int
    form_type: Optional[str] = None
    upload_channel: Optional[str] = None
    status: str
    created_at: Optional[str] = None  # 업로드 날짜 (ISO 형식)
    data_year: Optional[int] = None  # 문서 데이터 연도 (請求年月에서 추출)
    data_month: Optional[int] = None  # 문서 데이터 월 (請求年月에서 추출)
    is_answer_key_document: bool = False  # 정답지 생성 대상 여부 (true면 검토 탭에서 제외)
    analyzed_page_numbers: Optional[List[int]] = None  # 분석 완료된 페이지 번호 목록 (검토 탭에서 "분석 중" 구분용)


class DocumentListResponse(BaseModel):
    """문서 목록 응답 모델"""
    documents: List[DocumentResponse]
    total: int


@router.post("/upload", response_model=dict)
async def upload_documents(
    upload_channel: Optional[str] = Form(None, alias="upload_channel"),
    form_type: Optional[str] = Form(None, alias="form_type"),  # 하위 호환 (더 이상 upload_channel 결정에 사용하지 않음)
    files: List[UploadFile] = File(...),
    year: Optional[int] = Form(None),
    month: Optional[int] = Form(None),
    background_tasks: BackgroundTasks = None,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    """
    PDF 파일 업로드 및 처리
    
    Args:
        upload_channel: finet(엑셀) | mail(Azure OCR, 표 복원)
        form_type: 하위 호환 (01-06, 더 이상 upload_channel 추론에는 사용하지 않음)
        files: 업로드된 PDF 파일 리스트
        year: 연도 (선택사항)
        month: 월 (선택사항, 1-12)
    """
    # 옵션 1: 텍스트 추출 방식은 upload_channel 기준으로만 결정.
    # form_type만으로 channel을 추론하는 것은 지원하지 않는다.
    if not upload_channel or upload_channel not in ("finet", "mail"):
        raise HTTPException(
            status_code=400,
            detail="upload_channel (finet|mail) is required. form_type 파라미터만 보내는 방식은 더 이상 지원하지 않습니다.",
        )
    
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    
    # month 유효성 검사
    if month is not None and not (1 <= month <= 12):
        raise HTTPException(status_code=422, detail=f"Invalid month: {month}. Must be 1-12")
    
    # 세션 ID 생성 (임시로 파일명 기반)
    session_id = SessionManager.generate_session_id()
    
    results = []
    for uploaded_file in files:
        try:
            # 파일명에서 확장자 제거
            pdf_name = Path(uploaded_file.filename).stem
            
            # 파일 크기 확인
            file_bytes = await uploaded_file.read()
            if len(file_bytes) > settings.MAX_UPLOAD_SIZE:
                results.append({
                    "filename": uploaded_file.filename,
                    "status": "error",
                    "error": f"File size exceeds {settings.MAX_UPLOAD_SIZE / 1024 / 1024}MB"
                })
                continue
            
            # 파일이 이미 존재하는지 확인
            pdf_filename = f"{pdf_name}.pdf"
            doc_info = await db.run_sync(db.check_document_exists, pdf_filename)
            if doc_info['exists']:
                try:
                    def _update_doc_channel(database, ch, fn):
                        with database.get_connection() as conn:
                            cursor = conn.cursor()
                            cursor.execute("UPDATE documents_current SET upload_channel = %s WHERE pdf_filename = %s", (ch, fn))
                            cursor.execute("UPDATE documents_archive SET upload_channel = %s WHERE pdf_filename = %s", (ch, fn))
                            conn.commit()
                    await db.run_sync(_update_doc_channel, db, upload_channel, pdf_filename)
                except Exception:
                    pass
                results.append({
                    "filename": uploaded_file.filename,
                    "status": "exists",
                    "pages": doc_info.get('total_pages', 0)
                })
            else:
                # 새 파일: 처리 대기 상태로 추가
                results.append({
                    "filename": uploaded_file.filename,
                    "status": "pending",
                    "pdf_name": pdf_name
                })
                
                # 백그라운드에서 처리 시작
                if background_tasks:
                    background_tasks.add_task(
                        process_pdf_background,
                        file_bytes=file_bytes,
                        pdf_name=pdf_name,
                        upload_channel=upload_channel,
                        form_type=form_type,
                        session_id=session_id,
                        user_id=current_user["user_id"],
                        data_year=year,
                        data_month=month
                    )
        
        except Exception as e:
            results.append({
                "filename": uploaded_file.filename,
                "status": "error",
                "error": str(e)
            })
    
    filenames = [r.get("filename", "") for r in results]
    activity_log(current_user.get("username"), f"업로드: {', '.join(filenames)}")
    return {
        "message": "Files uploaded",
        "results": results,
        "session_id": session_id
    }


@router.post("/upload-with-bbox", response_model=dict)
async def upload_documents_with_bbox(
    upload_channel: Optional[str] = Form(None, alias="upload_channel"),
    form_type: Optional[str] = Form(None, alias="form_type"),  # 하위 호환 (더 이상 upload_channel 결정에 사용하지 않음)
    files: List[UploadFile] = File(...),
    year: Optional[int] = Form(None),
    month: Optional[int] = Form(None),
    background_tasks: BackgroundTasks = None,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    """
    PDF 업로드 후 좌표 포함 파싱. mail 채널에서 Azure(표 복원) + RAG+LLM, 필요 시 _word_indices → _bbox 부여.
    """
    # 옵션 1: 무조건 upload_channel로만 동작
    if not upload_channel or upload_channel not in ("finet", "mail"):
        raise HTTPException(
            status_code=400,
            detail="upload_channel (finet|mail) is required. form_type 파라미터만 보내는 방식은 더 이상 지원하지 않습니다.",
        )
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    if month is not None and not (1 <= month <= 12):
        raise HTTPException(status_code=422, detail=f"Invalid month: {month}. Must be 1-12")

    session_id = SessionManager.generate_session_id()
    results = []
    for uploaded_file in files:
        try:
            pdf_name = Path(uploaded_file.filename).stem
            file_bytes = await uploaded_file.read()
            if len(file_bytes) > settings.MAX_UPLOAD_SIZE:
                results.append({
                    "filename": uploaded_file.filename,
                    "status": "error",
                    "error": f"File size exceeds {settings.MAX_UPLOAD_SIZE / 1024 / 1024}MB"
                })
                continue
            pdf_filename = f"{pdf_name}.pdf"
            doc_info = await db.run_sync(db.check_document_exists, pdf_filename)
            if doc_info["exists"]:
                results.append({
                    "filename": uploaded_file.filename,
                    "status": "exists",
                    "pages": doc_info.get("total_pages", 0)
                })
            else:
                results.append({
                    "filename": uploaded_file.filename,
                    "status": "pending",
                    "pdf_name": pdf_name
                })
                if background_tasks:
                    background_tasks.add_task(
                        process_pdf_background,
                        file_bytes=file_bytes,
                        pdf_name=pdf_name,
                        upload_channel=upload_channel,
                        form_type=None,
                        session_id=session_id,
                        user_id=current_user["user_id"],
                        data_year=year,
                        data_month=month,
                        include_bbox=True,
                    )
        except Exception as e:
            results.append({
                "filename": uploaded_file.filename,
                "status": "error",
                "error": str(e)
            })
    filenames_bbox = [r.get("filename", "") for r in results]
    activity_log(current_user.get("username"), f"업로드(bbox): {', '.join(filenames_bbox)}")
    return {
        "message": "Files uploaded (with bbox)",
        "results": results,
        "session_id": session_id
    }


def _create_document_on_analysis_failure_sync(
    database,
    pdf_filename: str,
    total_pages: int,
    upload_channel: str,
    user_id: int,
    data_year: Optional[int],
    data_month: Optional[int],
):
    """1페이지 분석 실패 시 문서만 생성 (form_type=null). 검토 탭에서 미분류로 표시."""
    with database.get_connection() as conn:
        cursor = conn.cursor()
        if data_year and data_month:
            created_at = datetime(data_year, data_month, 1)
            cursor.execute("""
                INSERT INTO documents_current (pdf_filename, total_pages, form_type, upload_channel, created_by_user_id, updated_by_user_id, created_at, data_year, data_month)
                VALUES (%s, %s, NULL, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (pdf_filename) DO UPDATE SET total_pages = EXCLUDED.total_pages, form_type = COALESCE(documents_current.form_type, NULL),
                    upload_channel = EXCLUDED.upload_channel, updated_at = CURRENT_TIMESTAMP
            """, (pdf_filename, total_pages, upload_channel, user_id, user_id, created_at, data_year, data_month))
        else:
            cursor.execute("""
                INSERT INTO documents_current (pdf_filename, total_pages, form_type, upload_channel, created_by_user_id, updated_by_user_id)
                VALUES (%s, %s, NULL, %s, %s, %s)
                ON CONFLICT (pdf_filename) DO UPDATE SET total_pages = EXCLUDED.total_pages, form_type = COALESCE(documents_current.form_type, NULL),
                    upload_channel = EXCLUDED.upload_channel, updated_at = CURRENT_TIMESTAMP
            """, (pdf_filename, total_pages, upload_channel, user_id, user_id))
        conn.commit()


def _update_doc_after_upload_sync(
    database,
    upload_channel: str,
    user_id: int,
    data_year: Optional[int],
    data_month: Optional[int],
    pdf_filename: str,
):
    """업로드 완료 후 문서 메타 업데이트 (run_sync용 동기 함수). 이벤트 루프 블로킹 방지."""
    with database.get_connection() as conn:
        cursor = conn.cursor()
        if data_year and data_month:
            created_at = datetime(data_year, data_month, 1)
            cursor.execute("""
                UPDATE documents_current
                SET upload_channel = %s, created_at = %s, data_year = %s, data_month = %s,
                    created_by_user_id = COALESCE(created_by_user_id, %s)
                WHERE pdf_filename = %s
            """, (upload_channel, created_at, data_year, data_month, user_id, pdf_filename))
        else:
            cursor.execute("""
                UPDATE documents_current
                SET upload_channel = %s, created_by_user_id = COALESCE(created_by_user_id, %s)
                WHERE pdf_filename = %s
            """, (upload_channel, user_id, pdf_filename))
        conn.commit()
        cursor.execute("SELECT form_type FROM documents_current WHERE pdf_filename = %s LIMIT 1", (pdf_filename,))
        row = cursor.fetchone()
        if settings.DEBUG and row:
            print(f"[form_type] 업로드 완료: form_type={repr(row[0])}")


async def process_pdf_background(
    file_bytes: bytes,
    pdf_name: str,
    upload_channel: str,
    form_type: Optional[str],
    session_id: str,
    user_id: int,
    data_year: Optional[int] = None,
    data_month: Optional[int] = None,
    include_bbox: bool = False,
):
    """
    백그라운드에서 PDF 처리
    
    Args:
        file_bytes: PDF 파일 바이트 데이터
        pdf_name: PDF 파일명 (확장자 제외)
        form_type: 양식지 타입
        session_id: 세션 ID (WebSocket task_id로 사용)
    """
    pdf_path = None
    try:
        db = get_db()
        _ensure_phase1_rag_columns(db)
        main_loop = asyncio.get_event_loop()

        def progress_callback(page_num: int, total_pages: int, message: str):
            progress_data = {
                "type": "progress",
                "file_name": f"{pdf_name}.pdf",
                "current_page": page_num,
                "total_pages": total_pages,
                "message": message,
                "progress": page_num / total_pages if total_pages > 0 else 0
            }
            asyncio.run_coroutine_threadsafe(
                manager.send_progress(session_id, progress_data),
                main_loop
            )

        await manager.send_progress(session_id, {
            "type": "start",
            "file_name": f"{pdf_name}.pdf",
            "message": f"Processing {pdf_name}.pdf..."
        })

        pdf_path = SessionManager.save_pdf_file_from_bytes(
            file_bytes=file_bytes,
            pdf_name=pdf_name,
            session_id=session_id
        )

        pdf_filename = f"{pdf_name}.pdf"

        def _on_document_ready(total_pages: int, pil_images: list):
            """전체 이미지 변환 직후: 문서 행 생성 + 이미지 저장 → 검토 탭에서 즉시 문서 노출"""
            import io
            image_data_list = []
            for img in pil_images:
                if img is None:
                    image_data_list.append(None)
                    continue
                buf = io.BytesIO()
                if img.mode != "RGB":
                    img = img.convert("RGB")
                img.save(buf, format="JPEG", quality=95, optimize=True)
                image_data_list.append(buf.getvalue())
            db_sync = get_db()
            db_sync.create_document_with_images(
                pdf_filename=pdf_filename,
                total_pages=total_pages,
                image_data_list=image_data_list,
                upload_channel=upload_channel,
                user_id=user_id,
                data_year=data_year,
                data_month=data_month,
            )

        def _on_page_complete(page_number: int, page_json: dict):
            """페이지별 RAG+LLM 완료 시: DB 저장 + WebSocket으로 검토 탭 갱신 유도"""
            db_sync = get_db()
            db_sync.save_single_page_data(
                pdf_filename=pdf_filename,
                page_json=page_json,
                form_type=form_type,
                upload_channel=upload_channel,
                image_data=None,
            )
            asyncio.run_coroutine_threadsafe(
                manager.send_progress(
                    session_id,
                    {
                        "type": "page_complete",
                        "file_name": pdf_filename,
                        "page_number": page_number,
                    },
                ),
                main_loop,
            )

        user_sem = await _get_user_analysis_semaphore(user_id)
        async with user_sem:
            async with _global_analysis_semaphore:
                # 업로드 시: OCR·분석은 전체 페이지, 페이지 완료 시마다 DB 저장 + page_complete 전송
                success, pages, error_msg, elapsed_time = await main_loop.run_in_executor(
                    _analysis_executor,
                    lambda: PdfProcessor.process_pdf(
                        pdf_name=pdf_name,
                        pdf_path=str(pdf_path),
                        dpi=rag_config.dpi,
                        progress_callback=progress_callback,
                        form_type=form_type,
                        upload_channel=upload_channel,
                        user_id=user_id,
                        data_year=data_year,
                        data_month=data_month,
                        include_bbox=include_bbox,
                        page_numbers=None,
                        convert_all_images=False,
                        on_document_ready=_on_document_ready,
                        on_page_complete=_on_page_complete,
                    ),
                )

        if success:
            pdf_filename = f"{pdf_name}.pdf"
            try:
                db = get_db()
                await db.run_sync(
                    _update_doc_after_upload_sync,
                    db,
                    upload_channel,
                    user_id,
                    data_year,
                    data_month,
                    pdf_filename,
                )
            except Exception:
                pass

            # 완료 메시지 전송
            await manager.send_progress(session_id, {
                "type": "complete",
                "file_name": f"{pdf_name}.pdf",
                "pages": pages,
                "elapsed_time": elapsed_time,
                "message": f"Processing completed: {pages} pages in {elapsed_time:.1f}s"
            })
        else:
            # Phase 1: 1페이지 분석 실패 시에도 문서만 생성 (form_type=null)
            try:
                import fitz
                db = get_db()
                pdf_filename = f"{pdf_name}.pdf"
                with fitz.open(str(pdf_path)) as doc:
                    total_pages = len(doc)
                await db.run_sync(_create_document_on_analysis_failure_sync,
                    db, pdf_filename, total_pages, upload_channel, user_id, data_year, data_month)
            except Exception:
                pass
            await manager.send_progress(session_id, {
                "type": "error",
                "file_name": f"{pdf_name}.pdf",
                "error": error_msg,
                "message": f"Processing failed: {error_msg}"
            })
    
    except Exception as e:
        try:
            await manager.send_progress(session_id, {
                "type": "error",
                "file_name": f"{pdf_name}.pdf",
                "error": str(e),
                "message": f"Processing failed: {str(e)}"
            })
        except Exception:
            pass
    finally:
        # 처리 완료 후 temp 폴더의 PDF 파일 및 세션 디렉토리 정리
        # 이미지로 변환되어 static 폴더에 저장되므로 temp 폴더의 파일은 더 이상 필요 없음
        try:
            if pdf_path and pdf_path.exists():
                pdf_path.unlink()
            
            # 세션 디렉토리 내 모든 파일 정리
            if pdf_path:
                pdfs_dir = pdf_path.parent  # temp/{session_id}/pdfs
                session_dir = pdfs_dir.parent  # temp/{session_id}
                
                # pdfs 디렉토리 내 모든 파일 삭제
                if pdfs_dir.exists():
                    for file in pdfs_dir.iterdir():
                        if file.is_file():
                            file.unlink()
                    # pdfs 디렉토리가 비어있으면 삭제
                    if not any(pdfs_dir.iterdir()):
                        pdfs_dir.rmdir()
                
                # 세션 디렉토리 내 다른 파일들도 정리 (OCR 결과 JSON 등)
                if session_dir.exists():
                    for item in session_dir.iterdir():
                        if item.is_file():
                            item.unlink()
                    # 세션 디렉토리가 비어있으면 삭제
                    if not any(session_dir.iterdir()):
                        session_dir.rmdir()
        except Exception:
            pass


@router.get("/", response_model=DocumentListResponse)
async def get_documents(
    form_type: Optional[str] = None,
    upload_channel: Optional[str] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
    is_answer_key_document: Optional[bool] = None,
    exclude_answer_key: Optional[bool] = None,
    exclude_img_seed: bool = True,
    db=Depends(get_db)
):
    """
    문서 목록 조회 (current/archive 테이블 사용).
    exclude_img_seed 기본 True: created_by_user_id IS NULL(img 시드) 문서 제외 (업로드/검토 탭 기본).
    현황 탭 등 전체 포함 필요 시 exclude_img_seed=false 로 호출.
    """
    _ensure_phase1_rag_columns(db)
    try:
        def _get_documents_sync(database, **kwargs):
            rows = query_documents_table(database, **kwargs)
            return _build_document_list_from_rows(database, rows, kwargs.get("year"), kwargs.get("month"))
        documents = await db.run_sync(
            _get_documents_sync,
            db,
            form_type=form_type,
            upload_channel=upload_channel,
            year=year,
            month=month,
            is_answer_key_document=is_answer_key_document,
            exclude_answer_key=exclude_answer_key,
            exclude_img_seed=exclude_img_seed,
        )
        logging.info(
            "get_documents: documents=%s (params: year=%s, month=%s)",
            len(documents), year, month,
        )
        return DocumentListResponse(documents=documents, total=len(documents))
    
    except Exception as e:
        logging.exception("get_documents failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


def _extract_pdf_filenames_from_index_metadata(meta) -> list:
    """rag_vector_index.metadata_json 에서 pdf_filename 목록 추출."""
    if meta is None:
        return []
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            return []
    if not isinstance(meta, dict):
        return []
    metadata_dict = meta.get("metadata") or meta.get("Metadata") or {}
    pdf_names = set()
    for _doc_id, doc_data in (metadata_dict or {}).items():
        if not isinstance(doc_data, dict):
            continue
        inner = doc_data.get("metadata") or doc_data.get("Metadata") or {}
        pn = (inner or {}).get("pdf_name") or (inner or {}).get("pdf_filename")
        if pn:
            pdf_names.add(pn)
    return [
        p if (p and str(p).lower().endswith(".pdf")) else f"{p}.pdf"
        for p in pdf_names
    ]


@router.get("/in-vector-index")
async def get_documents_in_vector_index(db=Depends(get_db)):
    """
    벡터 DB 등록 문서(pdf_filename) 목록 반환.
    - rag_page_embeddings(pgvector)에 있는 문서 + rag_vector_index 메타데이터(FAISS) 목록 합침.
    """
    try:
        def _fetch_vector_index_names_sync(database):
            names = set()
            with database.get_connection() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("SELECT DISTINCT pdf_filename FROM rag_page_embeddings")
                    for r in cursor.fetchall():
                        if r and r[0]:
                            names.add(r[0])
                except Exception:
                    pass
                cursor.execute("SELECT metadata_json FROM rag_vector_index WHERE index_name = 'base' AND (form_type IS NULL OR form_type = '') ORDER BY updated_at DESC LIMIT 1")
                row = cursor.fetchone()
            if row and row[0]:
                for p in _extract_pdf_filenames_from_index_metadata(row[0]):
                    if p:
                        names.add(p)
            return {"pdf_filenames": sorted(names)}
        return await db.run_sync(_fetch_vector_index_names_sync, db)
    except Exception:
        return {"pdf_filenames": []}


def _query_analyzed_page_numbers_batch(db, pdf_filenames: List[str]) -> Dict[str, List[int]]:
    """문서별 분석 완료 페이지 번호 목록 배치 조회. 반환: { pdf_filename: [page_number, ...] }"""
    if not pdf_filenames:
        return {}
    out = {fn: [] for fn in pdf_filenames}
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT pdf_filename, page_number FROM page_data_current
                WHERE pdf_filename = ANY(%s) ORDER BY pdf_filename, page_number
                """,
                (pdf_filenames,),
            )
            for pdf_fn, page_no in cursor.fetchall():
                out.setdefault(pdf_fn, []).append(page_no)
    except Exception:
        pass
    return out


def _build_document_list_from_rows(db, rows, year=None, month=None) -> List:
    """query_documents_table 결과 rows를 DocumentResponse 리스트로 변환 (get_documents / for_answer_key_tab 공용)."""
    if not rows:
        return []
    pdf_filenames = [row[0] for row in rows]
    page_meta_rows = query_page_meta_batch(db, pdf_filenames, year=year, month=month)
    analyzed_pages_map = _query_analyzed_page_numbers_batch(db, pdf_filenames)
    documents = []
    for row in rows:
        pdf_filename = row[0]
        total_pages = row[1]
        row_form_type = row[2]
        row_upload_channel = row[3] if len(row) > 3 else None
        created_at = row[4] if len(row) > 4 else row[3] if len(row) == 4 else None
        data_year = row[5] if len(row) > 5 else (row[4] if len(row) > 4 else None)
        data_month = row[6] if len(row) > 6 else (row[5] if len(row) > 5 else None)
        is_answer_key_document = bool(row[7]) if len(row) > 7 else False
        created_at_str = None
        if created_at:
            if isinstance(created_at, str):
                created_at_str = created_at
            elif isinstance(created_at, datetime):
                created_at_str = created_at.isoformat()
            else:
                try:
                    created_at_str = str(created_at)
                except Exception:
                    created_at_str = None
        if not data_year or not data_month:
            for page_filename, page_meta_data in page_meta_rows:
                if page_filename == pdf_filename and page_meta_data:
                    try:
                        page_meta = json.loads(page_meta_data) if isinstance(page_meta_data, str) else page_meta_data
                        document_meta = page_meta.get('document_meta', {})
                        if isinstance(document_meta, str):
                            document_meta = json.loads(document_meta)
                        billing_date = document_meta.get('請求年月') if isinstance(document_meta, dict) else page_meta.get('請求年月')
                        if billing_date:
                            year_month = extract_year_month_from_billing_date(billing_date)
                            if year_month:
                                data_year = data_year or year_month[0]
                                data_month = data_month or year_month[1]
                                break
                    except Exception:
                        pass
        documents.append(DocumentResponse(
            pdf_filename=pdf_filename,
            total_pages=total_pages,
            form_type=row_form_type,
            upload_channel=row_upload_channel,
            status="completed",
            created_at=created_at_str,
            data_year=data_year,
            data_month=data_month,
            is_answer_key_document=is_answer_key_document,
            analyzed_page_numbers=analyzed_pages_map.get(pdf_filename),
        ))
    return documents


@router.get("/for-answer-key-tab", response_model=DocumentListResponse)
async def get_documents_for_answer_key_tab(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    """
    正解表作成タブ用の文書一覧。管理者は全正解表対象、一般ユーザーは自分が指定した文書のみ。
    (DB 접근은 run_sync 내부에서만 수행해 이벤트 루프 블로킹 방지)
    """
    user_id: int = current_user.get("user_id")
    is_admin = current_user.get("username") == "admin" or bool(current_user.get("is_admin"))
    def _for_answer_key_tab_sync(database, uid, admin: bool):
        _ensure_answer_key_designated_by_column(database)
        rows = query_documents_table(
            database,
            is_answer_key_document=True,
            answer_key_designated_by_user_id=None if admin else uid,
            exclude_img_seed=True,
        )
        return _build_document_list_from_rows(database, rows)
    documents = await db.run_sync(_for_answer_key_tab_sync, db, user_id, is_admin)
    return DocumentListResponse(documents=documents, total=len(documents))


def _query_page_role_counts(db) -> Tuple[dict, dict]:
    """
    Returns (totals, by_doc).
    totals: { "cover": N, "detail": N, "summary": N, "reply": N }
    by_doc: { pdf_filename: { "cover": n, "detail": n, ... } }
    """
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            WITH role_counts AS (
                SELECT pdf_filename, page_role, COUNT(*) AS cnt
                FROM page_data_current
                WHERE page_role IS NOT NULL AND page_role != ''
                GROUP BY pdf_filename, page_role
                UNION ALL
                SELECT pdf_filename, page_role, COUNT(*) AS cnt
                FROM page_data_archive
                WHERE page_role IS NOT NULL AND page_role != ''
                GROUP BY pdf_filename, page_role
            )
            SELECT pdf_filename, page_role, SUM(cnt)::int AS cnt
            FROM role_counts
            GROUP BY pdf_filename, page_role
        """)
        rows = cursor.fetchall()
    totals = {"cover": 0, "detail": 0, "summary": 0, "reply": 0}
    by_doc = {}
    for pdf_filename, page_role, cnt in rows:
        role = (page_role or "").strip().lower()
        if role not in totals:
            totals[role] = 0
        totals[role] += cnt
        if pdf_filename not in by_doc:
            by_doc[pdf_filename] = {"cover": 0, "detail": 0, "summary": 0, "reply": 0}
        if role in by_doc[pdf_filename]:
            by_doc[pdf_filename][role] += cnt
        else:
            by_doc[pdf_filename][role] = cnt
    return totals, by_doc


@router.get("/overview")
async def get_documents_overview(
    answer_key_only: bool = False,
    db=Depends(get_db)
):
    """
    文書一覧と様式マッピング・ページ役割(Cover/Detail/Summary/Reply)別件数を返す。
    """
    try:
        def _overview_sync(database, answer_key_only: bool):
            rows = query_documents_table(database, is_answer_key_document=True if answer_key_only else None)
            totals, by_doc = _query_page_role_counts(database)
            return rows, totals, by_doc
        rows, totals, by_doc = await db.run_sync(_overview_sync, db, answer_key_only)
        documents = []
        for row in rows:
            pdf_filename = row[0]
            total_pages = row[1]
            form_type = row[2]
            is_ans = bool(row[7]) if len(row) > 7 else False
            role_counts = by_doc.get(pdf_filename) or {"cover": 0, "detail": 0, "summary": 0, "reply": 0}
            documents.append({
                "pdf_filename": pdf_filename,
                "form_type": form_type,
                "total_pages": total_pages,
                "is_answer_key_document": is_ans,
                "cover": role_counts.get("cover", 0),
                "detail": role_counts.get("detail", 0),
                "summary": role_counts.get("summary", 0),
                "reply": role_counts.get("reply", 0),
            })
        return {
            "page_role_totals": totals,
            "documents": documents,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _find_pdf_path_for_document(db, pdf_filename: str) -> Optional[Path]:
    """
    기존 문서용 PDF 파일 경로 찾기 (세션 temp, img 학습 폴더 순으로 검색).
    """
    pdf_name = pdf_filename[:-4] if pdf_filename.lower().endswith(".pdf") else pdf_filename
    from modules.utils.pdf_utils import find_pdf_path
    found = find_pdf_path(pdf_name)
    if found:
        p = Path(found)
        if p.exists():
            return p
    root = get_project_root()
    img_dir = root / "img"
    if img_dir.exists():
        doc = db.get_document(pdf_filename)
        if doc:
            ch = doc.get("upload_channel") or "mail"
            y, m = doc.get("data_year"), doc.get("data_month")
            if y and m:
                candidate = img_dir / ch / f"{y}-{m:02d}" / pdf_name / f"{pdf_name}.pdf"
                if candidate.exists():
                    return candidate
        for path in img_dir.rglob(f"{pdf_name}.pdf"):
            if path.is_file():
                return path
    return None


def _reanalyze_page_rag_only_sync(
    pdf_filename: str,
    page_number: int,
    form_type: Optional[str],
    ocr_text: str,
) -> Dict:
    """
    재분석 전용: OCR은 실행하지 않고 DB에서 받은 ocr_text로 RAG+LLM만 실행.
    Returns: page_json (page_number 포함). 디버그 출력은 debug2/{문서명}/ 에 저장.
    """
    from modules.utils.config import rag_config
    from modules.core.extractors.rag_extractor import extract_json_with_rag

    # 재분석 결과를 debug2에 저장 (최초 분석과 동일 경로)
    pdf_name = pdf_filename[:-4] if pdf_filename.lower().endswith(".pdf") else pdf_filename
    debug_base = get_project_root() / "debug2" / pdf_name
    debug_base.mkdir(parents=True, exist_ok=True)

    page_json = extract_json_with_rag(
        ocr_text=ocr_text,
        question=rag_config.question,
        model_name=rag_config.openai_model,
        temperature=0,
        top_k=rag_config.top_k,
        similarity_threshold=rag_config.similarity_threshold,
        debug_dir=str(debug_base),
        page_num=page_number,
        form_type=form_type,
        ocr_words=None,
        page_width=None,
        page_height=None,
        include_bbox=False,
    )
    if not isinstance(page_json, dict):
        raise ValueError(f"Unexpected response type: {type(page_json)}")
    page_json["page_number"] = page_number
    return page_json


def _get_ocr_text_from_db(db, pdf_filename: str, page_number: int) -> Optional[str]:
    """DB에서 해당 페이지의 ocr_text 반환 (컬럼 또는 page_meta._ocr_text). 없으면 None."""
    page_result = db.get_page_result(pdf_filename, page_number)
    if not page_result:
        return None
    ocr = page_result.get("ocr_text")
    if isinstance(ocr, str) and ocr.strip():
        return ocr.strip()
    meta = page_result.get("page_meta") or page_result
    ocr = meta.get("_ocr_text") if isinstance(meta, dict) else None
    if isinstance(ocr, str) and ocr.strip():
        return ocr.strip()
    return None


def _analyze_one_page_sync(
    db,
    pdf_filename: str,
    page_number: int,
    form_type: Optional[str],
    upload_channel: str,
) -> Tuple[int, Optional[Dict], Optional[str]]:
    """
    단일 페이지 재분석: OCR은 DB에서만 읽고, RAG+LLM만 실행 (analyze-from-page 병렬용).
    Returns: (page_number, page_json or None, error_message or None)
    """
    ocr_text = _get_ocr_text_from_db(db, pdf_filename, page_number)
    if not ocr_text:
        return (page_number, None, "OCR not in DB. Run initial analysis first.")
    try:
        page_json = _reanalyze_page_rag_only_sync(pdf_filename, page_number, form_type, ocr_text)
    except Exception as e:
        return (page_number, None, str(e))
    try:
        from modules.utils.fill_empty_values_utils import normalize_ditto_like_values_in_page_results, fill_empty_values_in_page_results
        from modules.utils.form2_rebate_utils import normalize_form2_rebate_conditions
        page_results = normalize_ditto_like_values_in_page_results([page_json])
        page_results = fill_empty_values_in_page_results(page_results, form_type=form_type)
        page_results = normalize_form2_rebate_conditions(page_results, form_type=form_type)
        page_json = page_results[0]
    except Exception:
        pass
    page_json["ocr_text"] = ocr_text  # 저장 시 DB에 유지
    return (page_number, page_json, None)


def _generate_all_page_images_sync(
    pdf_path_str: str,
    total_pages: int,
    pdf_filename: str,
    dpi: int,
    db,
) -> int:
    """
    PDF → 페이지 이미지 생성·파일 저장·DB INSERT를 동기로 수행.
    generate_page_images에서 asyncio.to_thread로 호출해 이벤트 루프 블로킹 방지.
    Returns: 저장한 페이지 수
    """
    import io
    import fitz
    from PIL import Image

    doc_fitz = fitz.open(pdf_path_str)
    try:
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        saved = 0
        for page_idx in range(min(len(doc_fitz), total_pages)):
            page_num = page_idx + 1
            page = doc_fitz.load_page(page_idx)
            pix = page.get_pixmap(matrix=matrix)
            img_bytes = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            jpeg_buf = io.BytesIO()
            img.save(jpeg_buf, format="JPEG", quality=95, optimize=True)
            image_data = jpeg_buf.getvalue()
            image_path = db.save_image_to_file(pdf_filename, page_num, image_data)
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO page_images_current
                    (pdf_filename, page_number, image_path, image_format, image_size)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (pdf_filename, page_number)
                    DO UPDATE SET
                        image_path = EXCLUDED.image_path,
                        image_format = EXCLUDED.image_format,
                        image_size = EXCLUDED.image_size,
                        created_at = CURRENT_TIMESTAMP
                """, (pdf_filename, page_num, image_path, "JPEG", len(image_data)))
                conn.commit()
            saved += 1
        return saved
    finally:
        doc_fitz.close()


@router.post("/{pdf_filename}/generate-page-images")
async def generate_page_images(
    pdf_filename: str,
    db=Depends(get_db),
):
    """
    이미지가 아직 없는 문서에 대해 PDF에서 페이지 이미지를 생성해 저장합니다.
    PDF는 세션 temp 또는 img 학습 폴더에서 찾습니다. 없으면 해당 문서를 다시 업로드해야 합니다.
    (무거운 I/O·DB 작업은 스레드에서 실행해 이벤트 루프 블로킹 방지)
    """
    doc = await db.run_sync(db.get_document, pdf_filename)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    total_pages = int(doc.get("total_pages") or 0)
    if total_pages <= 0:
        raise HTTPException(status_code=400, detail="Document has no pages")
    pdf_path = await db.run_sync(_find_pdf_path_for_document, db, pdf_filename)
    if not pdf_path or not pdf_path.exists():
        raise HTTPException(
            status_code=404,
            detail="PDFファイルが見つかりません。一覧から該当文書を再度アップロードして解析を実行してください。",
        )
    dpi = getattr(rag_config, "dpi", 200)
    try:
        saved = await asyncio.to_thread(
            _generate_all_page_images_sync,
            str(pdf_path),
            total_pages,
            pdf_filename,
            dpi,
            db,
        )
        return {"success": True, "message": f"Generated {saved} page images", "pages": saved}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _list_answer_keys_from_img():
    """img 폴더 스캔 → RAG DB 소스(Page*_answer.json 보유) 정답지 목록을 form_type별 반환."""
    from modules.core.build_faiss_db import find_pdf_pages
    root = get_project_root()
    img_dir = root / "img"
    if not img_dir.exists():
        return {"by_form_type": {}}
    form_folders = sorted(
        d.name for d in img_dir.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )
    seen = {}
    for form_folder in form_folders:
        pages = find_pdf_pages(img_dir, form_folder, verbose=False)
        for p in pages:
            ft = p.get("form_type") or ""
            pdf_name = p.get("pdf_name") or ""
            if not pdf_name:
                continue
            key = (ft, pdf_name)
            if key not in seen:
                ap = p.get("answer_json_path")
                try:
                    # 폴더 경로만 저장 (파일 경로가 아니라) — answer-json-from-img 가 폴더 기준으로 동작
                    parent = ap.parent if ap and getattr(ap, "parent", None) else None
                    rel = parent.relative_to(img_dir) if parent else None
                except Exception:
                    rel = None
                rel_str = str(rel).replace("\\", "/") if rel else None
                seen[key] = {"form_type": ft, "pdf_name": pdf_name, "relative_path": rel_str, "total_pages": 0}
            seen[key]["total_pages"] += 1
    by_form = {}
    for v in seen.values():
        ft = v["form_type"]
        if ft not in by_form:
            by_form[ft] = []
        by_form[ft].append({"pdf_name": v["pdf_name"], "relative_path": v["relative_path"], "total_pages": v["total_pages"]})
    for lst in by_form.values():
        lst.sort(key=lambda x: (x["pdf_name"] or ""))
    return {"by_form_type": by_form}


@router.get("/answer-keys-from-img")
async def get_answer_keys_from_img():
    """RAG DB 소스: img 폴더 내 Page*_answer.json 있는 문서 목록을 form_type별로 반환."""
    try:
        return _list_answer_keys_from_img()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# answer.json 스타일로 DB items 반환 시 사용 (get_document_answer_json / img 폴백 공통)
_ITEM_SYSTEM_KEYS = {"pdf_filename", "page_number", "item_order", "item_id", "version", "review_status"}


def _to_item_data_only(it: dict) -> dict:
    """merged item 또는 { item_data } 형태에서 item_data만 추출."""
    if not isinstance(it, dict):
        return it if it is not None else {}
    if "item_data" in it:
        return it.get("item_data") or {}
    return {k: v for k, v in it.items() if k not in _ITEM_SYSTEM_KEYS}


def _get_answer_pages_from_db(pdf_filename: str):
    """DB에서 문서의 페이지별 정답지(items는 item_data만) 반환. 문서 없으면 None."""
    db = get_db()
    doc = db.get_document(pdf_filename)
    if not doc:
        return None
    page_results = db.get_page_results(pdf_filename)
    pages = []
    for pr in page_results:
        items = pr.get("items") or []
        items_sorted = sorted(
            items,
            key=lambda x: int(x.get("item_order", 0)) if isinstance(x, dict) else 0,
        )
        items_plain = [_to_item_data_only(it) for it in items_sorted]
        page_obj = {k: v for k, v in pr.items() if k != "items"}
    # 페이지 번호 숫자 순 (1, 2, ... 10) — 문자열 정렬 시 Page10이 Page2보다 앞섬
        page_obj["items"] = items_plain
        pages.append(page_obj)
    pages.sort(key=lambda p: p.get("page_number") or 0)
    return pages


class AnalyzeSinglePageRequest(BaseModel):
    """단일 페이지 분석 요청 (Phase 1)"""
    pdf_filename: str
    page_number: int


@router.post("/analyze-single-page")
async def analyze_single_page(
    body: AnalyzeSinglePageRequest,
    db=Depends(get_db),
):
    """
    단일 페이지 재분석: OCR은 DB에서만 읽고, RAG+LLM만 실행 후 해당 페이지만 DB 저장.
    OCR은 최초 분석(업로드) 시에만 실행. 재분석은 RAG+LLM만 의미.
    """
    doc = db.get_document(body.pdf_filename)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    form_type = doc.get("form_type")
    upload_channel = doc.get("upload_channel") or "mail"

    ocr_text = await db.run_sync(_get_ocr_text_from_db, db, body.pdf_filename, body.page_number)
    if not ocr_text:
        raise HTTPException(
            status_code=400,
            detail="該当ページにOCR結果がありません。先に初回分析（アップロード）を実行してください。",
        )

    try:
        page_json = await asyncio.get_event_loop().run_in_executor(
            _analysis_executor,
            lambda: _reanalyze_page_rag_only_sync(
                body.pdf_filename, body.page_number, form_type, ocr_text
            ),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    try:
        from modules.utils.fill_empty_values_utils import normalize_ditto_like_values_in_page_results, fill_empty_values_in_page_results
        from modules.utils.form2_rebate_utils import normalize_form2_rebate_conditions
        page_results = normalize_ditto_like_values_in_page_results([page_json])
        page_results = fill_empty_values_in_page_results(page_results, form_type=form_type)
        page_results = normalize_form2_rebate_conditions(page_results, form_type=form_type)
        page_json = page_results[0]
    except Exception:
        pass
    page_json["ocr_text"] = ocr_text  # 저장 시 DB에 유지

    success = db.save_single_page_data(
        pdf_filename=body.pdf_filename,
        page_json=page_json,
        form_type=form_type,
        upload_channel=upload_channel,
        image_data=None,
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save page")
    return {"success": True, "page": page_json}


class AnalyzeFromPageRequest(BaseModel):
    """이 페이지 이후 전체 재분석 요청 (Phase 1)"""
    pdf_filename: str
    from_page_number: int


# 동시 재분석 페이지 수 상한 (API rate limit·리소스 고려)
_ANALYZE_FROM_PAGE_CONCURRENCY = min(5, max(1, int(os.getenv("ANALYZE_FROM_PAGE_CONCURRENCY", "4"))))


@router.post("/analyze-from-page")
async def analyze_from_page(
    body: AnalyzeFromPageRequest,
    db=Depends(get_db),
):
    """
    이 페이지(from_page_number)부터 마지막 페이지까지 병렬 재분석.
    학습 요청 시 해당 문서의 진행 중인 재분석은 중단됨 (6.3).
    """
    _ensure_phase1_rag_columns(db)
    doc = db.get_document(body.pdf_filename)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    total_pages = doc.get("total_pages") or 0
    if total_pages < 1:
        raise HTTPException(status_code=400, detail="Document has no pages")
    from_page = max(1, min(body.from_page_number, total_pages))
    form_type = doc.get("form_type")
    upload_channel = doc.get("upload_channel") or "mail"

    async with _reanalysis_lock:
        if body.pdf_filename in _reanalysis_cancel_events:
            raise HTTPException(status_code=409, detail="Re-analysis already in progress for this document")
        cancel_ev = asyncio.Event()
        _reanalysis_cancel_events[body.pdf_filename] = cancel_ev

    analyzed = []
    cancelled = False
    sem = asyncio.Semaphore(_ANALYZE_FROM_PAGE_CONCURRENCY)

    async def run_one(pg: int):
        nonlocal cancelled
        if cancelled:
            return (pg, None, "cancelled")
        async with sem:
            if cancel_ev.is_set():
                cancelled = True
                return (pg, None, "cancelled")
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(
                _analysis_executor,
                lambda: _analyze_one_page_sync(db, body.pdf_filename, pg, form_type, upload_channel),
            )
            pnum, pjson, err = res
            if cancel_ev.is_set():
                cancelled = True
                return (pnum, None, "cancelled")
            return (pnum, pjson, err)

    try:
        pages_to_run = list(range(from_page, total_pages + 1))
        tasks = [run_one(pg) for pg in pages_to_run]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                continue
            pnum, pjson, err = r
            if err == "cancelled":
                cancelled = True
                continue
            if pjson and not err:
                success = db.save_single_page_data(
                    pdf_filename=body.pdf_filename,
                    page_json=pjson,
                    form_type=form_type,
                    upload_channel=upload_channel,
                    image_data=None,
                )
                if success:
                    analyzed.append(pnum)
    finally:
        async with _reanalysis_lock:
            _reanalysis_cancel_events.pop(body.pdf_filename, None)

    return {
        "success": True,
        "analyzed": analyzed,
        "cancelled": cancelled,
        "from_page": from_page,
        "total_pages": total_pages,
    }


def request_cancel_reanalysis_for_document(pdf_filename: str) -> None:
    """학습 요청 시 해당 문서의 진행 중인 이 페이지 이후 전체 재분석을 중단시키기 위해 호출."""
    if pdf_filename in _reanalysis_cancel_events:
        _reanalysis_cancel_events[pdf_filename].set()


@router.get("/{pdf_filename}/answer-json")
async def get_document_answer_json(
    pdf_filename: str,
    db=Depends(get_db)
):
    """
    정답지 조회: 문서 전체의 answer.json 형태 (form_type별 기존 정답지 보기용).
    반환: { pdf_filename, form_type, pages: [ { page_number, page_role, ...page_meta, items }, ... ] }
    items는 item_data만 담은 리스트 (answer.json 스타일).
    """
    doc = db.get_document(pdf_filename)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    total_pages = doc.get("total_pages") or 0
    form_type = doc.get("form_type")
    page_results = db.get_page_results(pdf_filename)
    pages = []
    for pr in page_results:
        items = pr.get("items") or []
        items_sorted = sorted(
            items,
            key=lambda x: int(x.get("item_order", 0)) if isinstance(x, dict) else 0,
        )
        items_plain = [_to_item_data_only(it) for it in items_sorted]
        page_obj = {k: v for k, v in pr.items() if k not in ("items", "_ocr_text", "_rag_reference")}
        page_obj["items"] = items_plain
        pages.append(page_obj)
    pages.sort(key=lambda p: p.get("page_number") or 0)
    return {
        "pdf_filename": pdf_filename,
        "form_type": form_type,
        "total_pages": total_pages,
        "pages": pages,
    }


class SaveAnswerJsonRequest(BaseModel):
    """문서 전체 정답지 한 번에 저장 (DB만, 벡터 DB 없음). pages는 GET answer-json과 동일 형식."""
    pages: List[dict]  # [ { page_number, page_role?, page_meta?, items: [ item_data, ... ] }, ... ]


@router.put("/{pdf_filename}/answer-json")
async def save_document_answer_json(
    pdf_filename: str,
    body: SaveAnswerJsonRequest,
    current_user_id: int = Depends(get_current_user_id),
    db=Depends(get_db)
):
    """
    현재 상태를 문서 전체 answer-json으로 DB에 한 번에 반영.
    행마다 PUT 하지 않으므로 빠르고, refetch 시 null 덮어쓰기 없음.
    """
    _ensure_last_edited_columns(db)
    _ensure_phase1_rag_columns(db)
    doc = db.get_document(pdf_filename)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    form_type = doc.get("form_type")
    pages = body.pages if isinstance(body.pages, list) else []
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            first_item_keys = None
            for page_obj in pages:
                page_number = page_obj.get("page_number")
                if page_number is None:
                    continue
                page_number = int(page_number)
                page_role = (page_obj.get("page_role") or "detail").strip() or "detail"
                if page_role not in ("cover", "detail", "summary", "reply"):
                    page_role = "detail"
                page_meta = dict(page_obj.get("page_meta")) if isinstance(page_obj.get("page_meta"), dict) else {}
                page_meta.pop("_rag_reference", None)  # 정답지에 불필요, 저장하지 않음
                # 画面で表示済みのOCRを保存（ベクター登録時に再抽出しない）
                ocr_text = page_obj.get("ocr_text")
                if isinstance(ocr_text, str) and ocr_text.strip():
                    page_meta["_ocr_text"] = ocr_text.strip()
                page_meta_json = json.dumps(page_meta, ensure_ascii=False)
                items = page_obj.get("items") if isinstance(page_obj.get("items"), list) else []
                # items 비어있는데 detail이면 보정: 1페이지=cover, 그 외=summary
                if not items and page_role == "detail":
                    page_role = "cover" if page_number == 1 else "summary"

                # last_edited_at, last_edited_by_user_id: 그리드 保存 시 갱신 (Phase 1)
                cursor.execute("""
                    INSERT INTO page_data_current (pdf_filename, page_number, page_role, page_meta, last_edited_at, last_edited_by_user_id)
                    VALUES (%s, %s, %s, %s::json, CURRENT_TIMESTAMP, %s)
                    ON CONFLICT (pdf_filename, page_number)
                    DO UPDATE SET page_role = EXCLUDED.page_role, page_meta = EXCLUDED.page_meta,
                        last_edited_at = CURRENT_TIMESTAMP, last_edited_by_user_id = EXCLUDED.last_edited_by_user_id
                """, (pdf_filename, page_number, page_role, page_meta_json, current_user_id))

                cursor.execute(
                    "DELETE FROM items_current WHERE pdf_filename = %s AND page_number = %s",
                    (pdf_filename, page_number),
                )
                _unit_price_csv = get_project_root() / "database" / "csv" / "unit_price.csv"
                for item_order, item_dict in enumerate(items, 1):
                    if not isinstance(item_dict, dict):
                        continue
                    retail_code, dist_code = resolve_retail_dist(
                        item_dict.get("得意先"), item_dict.get("得意先コード")
                    )
                    if retail_code:
                        item_dict["小売先コード"] = retail_code
                    if dist_code:
                        item_dict["受注先コード"] = dist_code
                    product_result = resolve_product_and_prices(item_dict.get("商品名"), _unit_price_csv)
                    if product_result:
                        code, shikiri, honbu = product_result
                        if code:
                            item_dict["商品コード"] = code
                        if shikiri is not None:
                            item_dict["仕切"] = shikiri
                        if honbu is not None:
                            item_dict["本部長"] = honbu
                    upload_channel = doc.get("upload_channel")
                    apply_finet01_cs_irisu(item_dict, form_type, upload_channel)
                    apply_form04_mishu_decimal(item_dict, form_type)
                    # LLM이 タイプ를 null로 뱉어도 무조건 条件으로 DB 저장
                    _typ = item_dict.get("タイプ")
                    if _typ is None or (isinstance(_typ, str) and not (_typ or "").strip()):
                        item_dict["タイプ"] = "条件"
                    separated = db._separate_item_fields(item_dict, form_type=form_type)
                    item_data = separated.get("item_data") or {}
                    if first_item_keys is None and item_data:
                        first_item_keys = list(item_data.keys())
                    cursor.execute("""
                        INSERT INTO items_current (
                            pdf_filename, page_number, item_order,
                            first_review_checked, second_review_checked,
                            item_data
                        )
                        VALUES (%s, %s, %s, FALSE, FALSE, %s::json)
                    """, (
                        pdf_filename, page_number, item_order,
                        json.dumps(item_data, ensure_ascii=False),
                    ))
            # 이미 문서에 item_data_keys가 있으면 클라이언트 순서로 덮어쓰지 않음 (서버 LLM 저장 순서 유지)
            if first_item_keys:
                cursor.execute(
                    "SELECT document_metadata FROM documents_current WHERE pdf_filename = %s LIMIT 1",
                    (pdf_filename,),
                )
                row = cursor.fetchone()
                existing_keys = None
                if row and row[0]:
                    doc_meta = row[0] if isinstance(row[0], dict) else {}
                    existing_keys = doc_meta.get("item_data_keys")
                if existing_keys and isinstance(existing_keys, (list, tuple)) and len(existing_keys) > 0:
                    first_item_keys = None
            if first_item_keys:
                cursor.execute(
                    "SELECT document_metadata FROM documents_current WHERE pdf_filename = %s LIMIT 1",
                    (pdf_filename,),
                )
                row = cursor.fetchone()
                doc_meta = (row[0] or {}) if row and row[0] is not None else {}
                if not isinstance(doc_meta, dict):
                    doc_meta = {}
                doc_meta["item_data_keys"] = first_item_keys
                cursor.execute(
                    "UPDATE documents_current SET document_metadata = %s::json WHERE pdf_filename = %s",
                    (json.dumps(doc_meta, ensure_ascii=False), pdf_filename),
                )
            conn.commit()
        return {"success": True, "message": "Answer JSON saved (DB only)", "pages_count": len(pages)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{pdf_filename}")
async def get_document(
    pdf_filename: str,
    db=Depends(get_db)
):
    """
    특정 문서 정보 조회
    
    Args:
        pdf_filename: PDF 파일명
        db: 데이터베이스 인스턴스
    """
    try:
        doc = await db.run_sync(db.get_document, pdf_filename)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        created_at_str = None
        if doc.get('created_at'):
            created_at = doc['created_at']
            if isinstance(created_at, str):
                created_at_str = created_at
            elif isinstance(created_at, datetime):
                created_at_str = created_at.isoformat()
            else:
                try:
                    created_at_str = str(created_at)
                except Exception:
                    created_at_str = None
        year_month = await db.run_sync(get_document_year_month, db, pdf_filename)
        data_year = year_month[0] if year_month else None
        data_month = year_month[1] if year_month else None
        
        is_answer_key = bool(doc.get('is_answer_key_document', False))
        analyzed_page_numbers = await db.run_sync(
            _get_analyzed_page_numbers_sync, db, pdf_filename
        )
        return DocumentResponse(
            pdf_filename=doc['pdf_filename'],
            total_pages=doc['total_pages'],
            form_type=doc.get('form_type'),
            upload_channel=doc.get('upload_channel'),
            status="completed",
            created_at=created_at_str,
            data_year=data_year,
            data_month=data_month,
            is_answer_key_document=is_answer_key,
            analyzed_page_numbers=analyzed_page_numbers,
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{pdf_filename}/answer-key-designate")
async def designate_document_as_answer_key(
    pdf_filename: str,
    current_user_id: int = Depends(get_current_user_id),
    db=Depends(get_db)
):
    """
    문서를 정답지 생성 대상으로 지정（解答作成タブで編集・ベクターDB反映可能）。
    - 1・2次検討の完了有無にかかわらず指定可能（未完了時はフロントのモーダルで案内）
    - documents_current または documents_archive の is_answer_key_document = TRUE, answer_key_designated_by_user_id = 現在ユーザー
    - 該当文書の全ページの page_data に is_rag_candidate = TRUE
    """
    def _designate_answer_key_sync(database, uid: int, fn: str):
        _ensure_answer_key_designated_by_column(database)
        with database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE documents_current
                SET is_answer_key_document = TRUE, answer_key_designated_by_user_id = %s, updated_at = CURRENT_TIMESTAMP
                WHERE pdf_filename = %s
            """, (uid, fn))
            if cursor.rowcount > 0:
                cursor.execute("UPDATE page_data_current SET is_rag_candidate = TRUE, updated_at = CURRENT_TIMESTAMP WHERE pdf_filename = %s", (fn,))
            else:
                cursor.execute("""
                    UPDATE documents_archive
                    SET is_answer_key_document = TRUE, answer_key_designated_by_user_id = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE pdf_filename = %s
                """, (uid, fn))
                if cursor.rowcount == 0:
                    raise HTTPException(status_code=404, detail="Document not found in current or archive table")
                cursor.execute("UPDATE page_data_archive SET is_rag_candidate = TRUE, updated_at = CURRENT_TIMESTAMP WHERE pdf_filename = %s", (fn,))
            conn.commit()
    try:
        await db.run_sync(_designate_answer_key_sync, db, current_user_id, pdf_filename)
        return {"success": True, "message": "Document designated for answer key creation"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _revoke_answer_key_sync(database, pdf_filename: str):
    """정답지 지정 해제 DB 작업 (run_sync용)."""
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE documents_current
            SET is_answer_key_document = FALSE, answer_key_designated_by_user_id = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE pdf_filename = %s
        """, (pdf_filename,))
        if cursor.rowcount > 0:
            cursor.execute("""
                UPDATE page_data_current
                SET is_rag_candidate = FALSE, updated_at = CURRENT_TIMESTAMP
                WHERE pdf_filename = %s
            """, (pdf_filename,))
        else:
            cursor.execute("""
                UPDATE documents_archive
                SET is_answer_key_document = FALSE, answer_key_designated_by_user_id = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE pdf_filename = %s
            """, (pdf_filename,))
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Document not found in current or archive table")
            cursor.execute("""
                UPDATE page_data_archive
                SET is_rag_candidate = FALSE, updated_at = CURRENT_TIMESTAMP
                WHERE pdf_filename = %s
            """, (pdf_filename,))
        conn.commit()


@router.post("/{pdf_filename}/answer-key-revoke")
async def revoke_document_answer_key(
    pdf_filename: str,
    db=Depends(get_db)
):
    """
    문서의 정답지 생성 대상 지정 해제 (검토 탭에서 다시 표시됨)
    - documents_current 또는 documents_archive의 is_answer_key_document = FALSE, answer_key_designated_by_user_id = NULL
    - 해당 문서의 모든 페이지에 page_data의 is_rag_candidate = FALSE
    """
    try:
        await db.run_sync(_revoke_answer_key_sync, db, pdf_filename)
        return {"success": True, "message": "Document revoked from answer key creation"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{pdf_filename}/pages/{page_number:int}/generate-answer-rag")
async def generate_answer_with_rag(
    pdf_filename: str,
    page_number: int,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    """
    Azure OCR(표 복원) + RAG+LLM으로 해당 페이지의 정답지(items) 생성.
    표 구조가 보존된 OCR 텍스트를 사용하므로, Vision 대신 이 경로를 쓰면 열/행 구조가 안정적.
    """
    try:
        ocr_text = await asyncio.to_thread(_get_ocr_text_azure_sync, db, pdf_filename, page_number)
        if not ocr_text:
            raise HTTPException(
                status_code=404,
                detail="OCR text not found. Save page image or run RAG extraction first."
            )
        doc = db.get_document(pdf_filename)
        form_type = doc.get("form_type") if doc else None
        debug_dir = str(_answer_key_debug_dir(pdf_filename))
        from modules.core.extractors.rag_extractor import extract_json_with_rag
        result = await asyncio.to_thread(
            extract_json_with_rag,
            ocr_text=ocr_text,
            form_type=form_type,
            debug_dir=debug_dir,
            page_num=page_number,
        )
        items = result.get("items")
        if items is None:
            items = []
        if not isinstance(items, list):
            items = []
        page_role = result.get("page_role") or "detail"
        # items 비어있는데 detail이면 보정: 1페이지=cover, 그 외=summary
        if not items and page_role == "detail":
            page_role = "cover" if page_number == 1 else "summary"
        # 정답지 포맷에는 RAG 내부 메타 제외 (answer.json 스타일만)
        exclude_from_page_meta = ("items", "page_role", "_rag_reference")
        page_meta = {
            k: v for k, v in result.items()
            if k not in exclude_from_page_meta and v is not None
        }
        activity_log(current_user.get("username"), f"분석(RAG): {pdf_filename} p.{page_number}")
        return {
            "success": True,
            "page_number": page_number,
            "page_role": page_role,
            "page_meta": page_meta if page_meta else None,
            "items": items,
            "provider": "rag",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{pdf_filename}/pages/{page_number:int}/generate-answer-gpt")
async def generate_answer_with_gpt(
    pdf_filename: str,
    page_number: int,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    동일한 프롬프트로 GPT Vision에 이미지를 넘겨 정답지(items) 생성. 모델은 config.openai_model 사용.
    """
    try:
        from PIL import Image
        from openai import OpenAI
        from modules.utils.config import load_gemini_prompt, get_gemini_prompt_path

        image_path = db.get_page_image_path(pdf_filename, page_number)
        if not image_path:
            raise HTTPException(status_code=404, detail="Page image not found")
        full_path = Path(image_path) if Path(image_path).is_absolute() else get_project_root() / image_path
        if not full_path.exists():
            raise HTTPException(status_code=404, detail="Page image not found")
        image = Image.open(full_path).convert("RGB")
        # API 크기 제한 고려해 리사이즈 (1200 기준)
        max_size = 1200
        w, h = image.size
        if w > max_size or h > max_size:
            ratio = min(max_size / w, max_size / h)
            image = image.resize((int(w * ratio), int(h * ratio)), Image.Resampling.LANCZOS)
        buf = BytesIO()
        image.save(buf, format="JPEG", quality=85)
        b64 = base64.standard_b64encode(buf.getvalue()).decode("ascii")

        prompt = load_gemini_prompt()
        api_key = getattr(settings, "openai_api_key", None) or __import__("os").getenv("OPENAI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY가 설정되지 않았습니다.")

        from modules.utils.llm_retry import call_with_retry
        client = OpenAI(api_key=api_key)
        model = rag_config.openai_model

        def _gpt_create():
            return call_with_retry(
                lambda: client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                            ],
                        }
                    ],
                    max_completion_tokens=4096,
                )
            )
        response = await asyncio.to_thread(_gpt_create)
        raw_text = (response.choices[0].message.content or "").strip()
        if not raw_text:
            raise HTTPException(status_code=502, detail="GPT returned empty content")

        # 디버깅: debug/answer_key/{문서명}/ 에 프롬프트·원문·파싱 결과 저장
        try:
            debug_path = _answer_key_debug_dir(pdf_filename)
            debug_path.mkdir(parents=True, exist_ok=True)
            (debug_path / f"page_{page_number}_prompt.txt").write_text(prompt, encoding="utf-8")
            (debug_path / f"page_{page_number}_response.txt").write_text(raw_text, encoding="utf-8")
        except Exception as e:
            print(f"[generate_answer_with_gpt] debug 저장 실패: {e}")

        json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if not json_match:
            raise HTTPException(status_code=502, detail="GPT response did not contain JSON")
        result = json.loads(json_match.group())

        try:
            debug_path = _answer_key_debug_dir(pdf_filename)
            (debug_path / f"page_{page_number}_response_parsed.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            print(f"[generate_answer_with_gpt] debug parsed 저장 실패: {e}")

        items = result.get("items")
        if items is None:
            items = []
        if not isinstance(items, list):
            items = []

        try:
            _prompt_name = get_gemini_prompt_path().name
            _first_keys = list(items[0].keys()) if items and isinstance(items[0], dict) else []
            print(f"[generate_answer_with_gpt] model={model} prompt_file={_prompt_name} first_item_keys={_first_keys}")
        except Exception:
            pass

        page_role = result.get("page_role") or "detail"
        # items 비어있는데 detail이면 보정: 1페이지=cover, 그 외=summary
        if not items and page_role == "detail":
            page_role = "cover" if page_number == 1 else "summary"
        page_meta = {
            k: v for k, v in result.items()
            if k not in ("items", "page_role") and v is not None
        }
        activity_log(current_user.get("username"), f"분석(GPT): {pdf_filename} p.{page_number}")
        return {
            "success": True,
            "page_number": page_number,
            "page_role": page_role,
            "page_meta": page_meta if page_meta else None,
            "items": items,
            "model": model,
        }
    except HTTPException:
        raise
    except ValueError as e:
        if "OPENAI_API_KEY" in str(e):
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY가 설정되지 않았습니다.")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class CreateItemsFromAnswerRequest(BaseModel):
    """Gemini 생성 결과로 items 생성 요청"""
    items: list
    page_role: Optional[str] = "detail"
    page_meta: Optional[dict] = None


def _create_items_from_answer_sync(
    database, pdf_filename: str, page_number: int,
    items: list, page_role: str, page_meta_json: Optional[str]
):
    """정답지 결과로 items DB 저장 (run_sync용). 이벤트 루프 블로킹 방지."""
    # items 비어있는데 detail이면 보정: 1페이지=cover, 그 외=summary
    if not items and page_role == "detail":
        page_role = "cover" if page_number == 1 else "summary"
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM documents_current WHERE pdf_filename = %s LIMIT 1",
            (pdf_filename,)
        )
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Document not found")
        if page_meta_json:
            cursor.execute("""
                INSERT INTO page_data_current (pdf_filename, page_number, page_role, page_meta)
                VALUES (%s, %s, %s, %s::json)
                ON CONFLICT (pdf_filename, page_number)
                DO UPDATE SET
                    page_role = COALESCE(EXCLUDED.page_role, page_data_current.page_role),
                    page_meta = COALESCE(EXCLUDED.page_meta, page_data_current.page_meta)
            """, (pdf_filename, page_number, page_role, page_meta_json))
        else:
            cursor.execute("""
                INSERT INTO page_data_current (pdf_filename, page_number, page_role)
                VALUES (%s, %s, %s)
                ON CONFLICT (pdf_filename, page_number)
                DO UPDATE SET page_role = COALESCE(EXCLUDED.page_role, page_data_current.page_role)
            """, (pdf_filename, page_number, page_role))
        cursor.execute(
            "SELECT form_type, upload_channel FROM documents_current WHERE pdf_filename = %s LIMIT 1",
            (pdf_filename,)
        )
        row = cursor.fetchone()
        form_type = row[0] if row and row[0] else None
        upload_channel = row[1] if row and len(row) > 1 else None
        _unit_price_csv = get_project_root() / "database" / "csv" / "unit_price.csv"
        for item_order, item_dict in enumerate(items, 1):
            if not isinstance(item_dict, dict):
                continue
            retail_code, dist_code = resolve_retail_dist(
                item_dict.get("得意先"), item_dict.get("得意先コード")
            )
            if retail_code:
                item_dict["小売先コード"] = retail_code
            if dist_code:
                item_dict["受注先コード"] = dist_code
            product_result = resolve_product_and_prices(item_dict.get("商品名"), _unit_price_csv)
            if product_result:
                code, shikiri, honbu = product_result
                if code:
                    item_dict["商品コード"] = code
                if shikiri is not None:
                    item_dict["仕切"] = shikiri
                if honbu is not None:
                    item_dict["本部長"] = honbu
            apply_finet01_cs_irisu(item_dict, form_type, upload_channel)
            apply_form04_mishu_decimal(item_dict, form_type)
            # LLM이 タイプ를 null로 뱉어도 무조건 条件으로 DB 저장
            _typ = item_dict.get("タイプ")
            if _typ is None or (isinstance(_typ, str) and not (_typ or "").strip()):
                item_dict["タイプ"] = "条件"
            separated = database._separate_item_fields(item_dict, form_type=form_type)
            item_data = separated.get("item_data") or {}
            customer = separated.get("customer")
            cursor.execute("""
                INSERT INTO items_current (
                    pdf_filename, page_number, item_order,
                    customer,
                    first_review_checked, second_review_checked,
                    item_data
                )
                VALUES (%s, %s, %s, %s, FALSE, FALSE, %s::json)
            """, (
                pdf_filename, page_number, item_order,
                customer,
                json.dumps(item_data, ensure_ascii=False)
            ))
        if items and isinstance(items[0], dict):
            item_data_keys = list(items[0].keys())
            if item_data_keys:
                cursor.execute(
                    "SELECT document_metadata FROM documents_current WHERE pdf_filename = %s LIMIT 1",
                    (pdf_filename,),
                )
                row = cursor.fetchone()
                doc_meta = (row[0] or {}) if row and row[0] is not None else {}
                if not isinstance(doc_meta, dict):
                    doc_meta = {}
                doc_meta["item_data_keys"] = item_data_keys
                cursor.execute(
                    "UPDATE documents_current SET document_metadata = %s::json WHERE pdf_filename = %s",
                    (json.dumps(doc_meta, ensure_ascii=False), pdf_filename),
                )
        conn.commit()
    return {"success": True, "created_count": len(items), "page_number": page_number}


class GenerateItemsFromTemplateRequest(BaseModel):
    """첫 행(템플릿)으로 나머지 행 LLM 생성 요청. 모델은 config.openai_model 사용."""
    template_item: dict  # 한 행의 키-값 (키 추가/삭제/편집 가능)


def _create_items_from_template_sync(database, pdf_filename: str, page_number: int, items: list, page_role: str):
    """템플릿/GPT 결과로 items DB 저장 (run_sync용). 이벤트 루프 블로킹 방지."""
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM documents_current WHERE pdf_filename = %s LIMIT 1",
            (pdf_filename,)
        )
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Document not found")
        cursor.execute(
            "DELETE FROM items_current WHERE pdf_filename = %s AND page_number = %s",
            (pdf_filename, page_number)
        )
        cursor.execute("""
            INSERT INTO page_data_current (pdf_filename, page_number, page_role)
            VALUES (%s, %s, %s)
            ON CONFLICT (pdf_filename, page_number)
            DO UPDATE SET page_role = COALESCE(EXCLUDED.page_role, page_data_current.page_role)
        """, (pdf_filename, page_number, page_role))
        cursor.execute(
            "SELECT form_type, upload_channel FROM documents_current WHERE pdf_filename = %s LIMIT 1",
            (pdf_filename,)
        )
        row = cursor.fetchone()
        form_type = row[0] if row and row[0] else None
        upload_channel = row[1] if row and len(row) > 1 else None
        _unit_price_csv = get_project_root() / "database" / "csv" / "unit_price.csv"
        for item_order, item_dict in enumerate(items, 1):
            if not isinstance(item_dict, dict):
                continue
            retail_code, dist_code = resolve_retail_dist(
                item_dict.get("得意先"), item_dict.get("得意先コード")
            )
            if retail_code:
                item_dict["小売先コード"] = retail_code
            if dist_code:
                item_dict["受注先コード"] = dist_code
            product_result = resolve_product_and_prices(item_dict.get("商品名"), _unit_price_csv)
            if product_result:
                code, shikiri, honbu = product_result
                if code:
                    item_dict["商品コード"] = code
                if shikiri is not None:
                    item_dict["仕切"] = shikiri
                if honbu is not None:
                    item_dict["本部長"] = honbu
            apply_finet01_cs_irisu(item_dict, form_type, upload_channel)
            apply_form04_mishu_decimal(item_dict, form_type)
            # LLM이 タイプ를 null로 뱉어도 무조건 条件으로 DB 저장
            _typ = item_dict.get("タイプ")
            if _typ is None or (isinstance(_typ, str) and not (_typ or "").strip()):
                item_dict["タイプ"] = "条件"
            separated = database._separate_item_fields(item_dict, form_type=form_type)
            item_data = separated.get("item_data") or {}
            cursor.execute("""
                INSERT INTO items_current (
                    pdf_filename, page_number, item_order,
                    first_review_checked, second_review_checked,
                    item_data
                )
                VALUES (%s, %s, %s, FALSE, FALSE, %s::json)
            """, (
                pdf_filename, page_number, item_order,
                json.dumps(item_data, ensure_ascii=False)
            ))
        conn.commit()
    return {
        "success": True,
        "page_number": page_number,
        "items_count": len(items),
        "items": items,
    }


@router.post("/{pdf_filename}/pages/{page_number:int}/generate-items-from-template")
async def generate_items_from_template(
    pdf_filename: str,
    page_number: int,
    body: GenerateItemsFromTemplateRequest,
    db=Depends(get_db),
):
    """
    첫 행(템플릿)만 사용자가 편집한 뒤, 선택한 모델(GPT 또는 Gemini) Vision으로 같은 키 구조의 나머지 행을 생성.
    """
    import json
    try:
        from PIL import Image

        template_item = body.template_item if isinstance(body.template_item, dict) else {}
        if not template_item:
            raise HTTPException(status_code=400, detail="template_item is required")

        image_path = db.get_page_image_path(pdf_filename, page_number)
        if not image_path:
            raise HTTPException(status_code=404, detail="Page image not found")
        full_path = Path(image_path) if Path(image_path).is_absolute() else get_project_root() / image_path
        if not full_path.exists():
            raise HTTPException(status_code=404, detail="Page image not found")
        image = Image.open(full_path).convert("RGB")
        max_size = 1200
        w, h = image.size
        if w > max_size or h > max_size:
            ratio = min(max_size / w, max_size / h)
            image = image.resize((int(w * ratio), int(h * ratio)), Image.Resampling.LANCZOS)

        from openai import OpenAI
        buf = BytesIO()
        image.save(buf, format="JPEG", quality=85)
        b64 = base64.standard_b64encode(buf.getvalue()).decode("ascii")
        template_json = json.dumps(template_item, ensure_ascii=False, indent=2)
        prompt = f"""You are given a document page image and ONE example row (template) with the following keys and values.
Your task: Look at the image and generate ALL rows on this page. Each row must have exactly the same keys as the template.
Output ONLY a single JSON object with key "items" (array of objects). No other text.

Template (one row, keys and example value):
{template_json}

Output format: {{ "items": [ {{ ... }}, {{ ... }}, ... ] }}
Use the same key names as the template. Fill values from the document for each row."""
        api_key = getattr(settings, "openai_api_key", None) or __import__("os").getenv("OPENAI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY가 설정되지 않았습니다.")
        from modules.utils.llm_retry import call_with_retry
        client = OpenAI(api_key=api_key)
        gpt_model = rag_config.openai_model

        def _gpt_create():
            return call_with_retry(
                lambda: client.chat.completions.create(
                    model=gpt_model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                            ],
                        }
                    ],
                    max_completion_tokens=4096,
                )
            )
        response = await asyncio.to_thread(_gpt_create)
        raw_text = (response.choices[0].message.content or "").strip()
        if not raw_text:
            raise HTTPException(status_code=502, detail="GPT returned empty content")
        json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        result = {"items": [], "page_role": "detail"}
        if json_match:
            try:
                result = json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        items = result.get("items") or []
        if not isinstance(items, list):
            items = []
        page_role = result.get("page_role") or "detail"
        if not items and page_role == "detail":
            page_role = "cover" if page_number == 1 else "summary"

        return await db.run_sync(
            _create_items_from_template_sync,
            db,
            pdf_filename,
            page_number,
            items,
            page_role,
        )
    except HTTPException:
        raise
    except ValueError as e:
        if "OPENAI_API_KEY" in str(e):
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY가 설정되지 않았습니다.")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{pdf_filename}/pages/{page_number:int}/create-items-from-answer")
async def create_items_from_answer(
    pdf_filename: str,
    page_number: int,
    body: CreateItemsFromAnswerRequest,
    db=Depends(get_db)
):
    """
    Gemini 생성 결과(items)로 해당 페이지에 items를 새로 생성.
    page_data가 없으면 생성하고, items를 순서대로 INSERT합니다.
    """
    import json
    try:
        items = body.items if isinstance(body.items, list) else []
        page_role = body.page_role or "detail"
        page_meta = body.page_meta if isinstance(body.page_meta, dict) else None
        page_meta_json = json.dumps(page_meta, ensure_ascii=False) if page_meta else None
        return await db.run_sync(
            _create_items_from_answer_sync,
            db,
            pdf_filename,
            page_number,
            items,
            page_role,
            page_meta_json,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class FormTypeUpdateRequest(BaseModel):
    """양식지 타입 변경 요청"""
    form_type: str


@router.patch("/{pdf_filename}/form-type")
async def update_document_form_type(
    pdf_filename: str,
    body: FormTypeUpdateRequest,
    db=Depends(get_db)
):
    """
    문서의 양식지 타입(form_type) 변경
    검토 탭에서 참조 양식지를 수동으로 수정할 때 사용
    """
    form_type = body.form_type.strip()
    if not form_type or len(form_type) > 10:
        raise HTTPException(status_code=400, detail="form_type must be 1-10 characters (e.g. 01, 02, 07)")

    try:
        await db.run_sync(_update_form_type_sync, db, pdf_filename, form_type)
        return {"form_type": form_type, "message": "Form type updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _update_form_type_sync(database, pdf_filename: str, form_type: str):
    """문서 form_type 업데이트 (run_sync용)."""
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE documents_current 
            SET form_type = %s, updated_at = CURRENT_TIMESTAMP
            WHERE pdf_filename = %s
        """, (form_type, pdf_filename))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Document not found")
        conn.commit()


def _delete_document_sync(database, pdf_filename: str):
    """문서 삭제 DB + static 이미지 삭제 (run_sync용)."""
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM documents_current WHERE pdf_filename = %s", (pdf_filename,))
        deleted_count = cursor.rowcount
        cursor.execute("DELETE FROM documents_archive WHERE pdf_filename = %s", (pdf_filename,))
        deleted_count += cursor.rowcount
        if deleted_count == 0:
            raise HTTPException(status_code=404, detail="Document not found")
        try:
            cursor.execute("DELETE FROM rag_page_embeddings WHERE pdf_filename = %s", (pdf_filename,))
        except Exception:
            pass
        conn.commit()
    _delete_static_images_for_document(pdf_filename)
    _delete_debug2_for_document(pdf_filename)


@router.delete("/{pdf_filename}")
async def delete_document(
    pdf_filename: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    """
    문서 삭제

    Args:
        pdf_filename: PDF 파일명
        db: 데이터베이스 인스턴스
    """
    try:
        await db.run_sync(_delete_document_sync, db, pdf_filename)
        activity_log(current_user.get("username"), f"문서 삭제: {pdf_filename}")
        return {"message": "Document deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 보관 기간(년). 이 기간을 초과한 문서는 purge 시 삭제됨.
RETENTION_YEARS = 1


def purge_old_documents_impl(db, retention_years: float = 1.0):
    """
    보관 기간을 초과한 문서를 DB와 static 이미지에서 삭제.
    스케줄러·API 공통 사용. db: DatabaseManager 인스턴스.
    """
    cutoff = datetime.utcnow() - timedelta(days=365 * retention_years)
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT pdf_filename FROM documents_current WHERE created_at < %s
        """, (cutoff,))
        current_list = [row[0] for row in cursor.fetchall()]
        cursor.execute("""
            SELECT pdf_filename FROM documents_archive WHERE created_at < %s
        """, (cutoff,))
        archive_list = [row[0] for row in cursor.fetchall()]
        pdf_filenames = list(dict.fromkeys(current_list + archive_list))
    if not pdf_filenames:
        return {"message": "No documents to purge", "deleted_count": 0, "deleted_files": []}
    with db.get_connection() as conn:
        cursor = conn.cursor()
        for pdf_filename in pdf_filenames:
            cursor.execute("DELETE FROM documents_current WHERE pdf_filename = %s", (pdf_filename,))
            cursor.execute("DELETE FROM documents_archive WHERE pdf_filename = %s", (pdf_filename,))
        conn.commit()
    for pdf_filename in pdf_filenames:
        _delete_static_images_for_document(pdf_filename)
        _delete_debug2_for_document(pdf_filename)
    return {
        "message": f"Purged documents older than {retention_years} year(s)",
        "deleted_count": len(pdf_filenames),
        "deleted_files": pdf_filenames,
    }


@router.post("/purge-old", response_model=dict)
async def purge_old_documents(
    retention_years: Optional[float] = 1,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    보관 기간(retention_years)을 초과한 문서를 DB와 static 이미지에서 삭제합니다.
    기본값: 최대 1년치 데이터만 유지 (1년 초과분 삭제).
    """
    try:
        years = retention_years if retention_years and retention_years > 0 else RETENTION_YEARS
        result = await db.run_sync(purge_old_documents_impl, db, years)
        activity_log(current_user.get("username"), f"구 문서 정리: {result.get('deleted_count', 0)}건")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{pdf_filename}/pages")
async def get_document_pages(
    pdf_filename: str,
    db=Depends(get_db)
):
    """
    문서의 페이지 목록 조회
    
    Args:
        pdf_filename: PDF 파일명
        db: 데이터베이스 인스턴스
    """
    try:
        page_results = db.get_page_results(pdf_filename)
        
        pages = []
        for page_result in page_results:
            pages.append({
                "page_number": page_result.get('page_number'),
                "items_count": len(page_result.get('items', []))
            })
        
        return {"pages": pages}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{pdf_filename}/pages/{page_number}/meta")
async def get_page_meta(
    pdf_filename: str,
    page_number: int,
    db=Depends(get_db)
):
    """
    특정 페이지의 메타데이터 조회 (page_meta)
    
    Args:
        pdf_filename: PDF 파일명
        page_number: 페이지 번호
        db: 데이터베이스 인스턴스
    """
    try:
        page_result = db.get_page_result(pdf_filename, page_number)
        
        if not page_result:
            raise HTTPException(status_code=404, detail="Page not found")
        
        # page_meta 추출: page_role, items, 내부 메타(_rag_reference 등) 제외
        page_role = page_result.get('page_role')
        page_meta = {}
        exclude_keys = {'page_role', 'items', 'page_number', 'customer', '_rag_reference'}
        for key, value in page_result.items():
            if key not in exclude_keys:
                page_meta[key] = value
        
        return {
            "page_role": page_role,
            "page_meta": page_meta
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class PageMetaUpdateRequest(BaseModel):
    """page_meta 업데이트 요청 (page_role 선택 편집 포함)"""
    page_meta: dict
    page_role: Optional[str] = None  # "cover" | "detail" | "summary" | "reply" — 지정 시 함께 갱신


@router.patch("/{pdf_filename}/pages/{page_number}/meta")
async def update_page_meta(
    pdf_filename: str,
    page_number: int,
    body: PageMetaUpdateRequest,
    db=Depends(get_db)
):
    """
    특정 페이지의 page_meta 업데이트 (정답지 생성 탭에서 편집 저장용).
    page_role이 있으면 유효한 값일 때만 DB의 page_role 컬럼도 갱신.
    """
    try:
        page_meta_json = json.dumps(body.page_meta, ensure_ascii=False) if body.page_meta else "{}"
        page_role = (body.page_role or "").strip().lower() or None
        if page_role and page_role not in ("cover", "detail", "summary", "reply"):
            page_role = None  # 무효 시 갱신하지 않음

        with db.get_connection() as conn:
            cursor = conn.cursor()
            if page_role is not None:
                cursor.execute("""
                    UPDATE page_data_current
                    SET page_meta = %s::json, page_role = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE pdf_filename = %s AND page_number = %s
                """, (page_meta_json, page_role, pdf_filename, page_number))
            else:
                cursor.execute("""
                    UPDATE page_data_current
                    SET page_meta = %s::json, updated_at = CURRENT_TIMESTAMP
                    WHERE pdf_filename = %s AND page_number = %s
                """, (page_meta_json, pdf_filename, page_number))
            if cursor.rowcount > 0:
                return {"success": True, "message": "page_meta updated"}
            if page_role is not None:
                cursor.execute("""
                    UPDATE page_data_archive
                    SET page_meta = %s::json, page_role = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE pdf_filename = %s AND page_number = %s
                """, (page_meta_json, page_role, pdf_filename, page_number))
            else:
                cursor.execute("""
                    UPDATE page_data_archive
                    SET page_meta = %s::json, updated_at = CURRENT_TIMESTAMP
                    WHERE pdf_filename = %s AND page_number = %s
                """, (page_meta_json, pdf_filename, page_number))
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Page not found")
        return {"success": True, "message": "page_meta updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
