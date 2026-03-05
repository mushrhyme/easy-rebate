"""
문서별 PDF 첨부 파일 API — static/attachments/{pdf_filename}/ 에 저장
"""
import re
import uuid
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Query

from modules.utils.config import get_project_root
from backend.core.auth import get_current_user_id

router = APIRouter()

# pdf_filename을 디렉터리명으로 사용할 수 있도록 정리 (경로/특수문자 제거)
def _safe_doc_dir(pdf_filename: str) -> str:
    s = re.sub(r'[^\w\-\.]', '_', pdf_filename)
    return s.strip('._') or "default"


def _attachments_dir(pdf_filename: str) -> Path:
    """문서별 첨부 디렉터리: static/attachments/{safe_pdf_filename}/"""
    root = get_project_root()
    base = root / "static" / "attachments"
    base.mkdir(parents=True, exist_ok=True)
    doc_dir = base / _safe_doc_dir(pdf_filename)
    doc_dir.mkdir(parents=True, exist_ok=True)
    return doc_dir


@router.get("/{pdf_filename}/attachments/list")
async def list_attachments(
    pdf_filename: str,
    _user_id: int = Depends(get_current_user_id),
):
    """
    해당 문서의 첨부 PDF 목록 반환.
    반환: { "files": [ { "name": "xxx.pdf", "url": "/static/attachments/.../xxx.pdf" } ] }
    """
    pdf_filename = unquote(pdf_filename)
    dir_path = _attachments_dir(pdf_filename)
    files = []
    for p in dir_path.iterdir():
        if p.is_file() and p.suffix.lower() == ".pdf":
            # URL: /static/attachments/{safe_dir}/{filename}
            rel = p.name
            safe_dir = _safe_doc_dir(pdf_filename)
            url = f"/static/attachments/{safe_dir}/{rel}"
            files.append({"name": rel, "url": url})
    files.sort(key=lambda x: x["name"])
    return {"files": files}


@router.post("/{pdf_filename}/attachments/upload")
async def upload_attachment(
    pdf_filename: str,
    file: UploadFile = File(...),
    _user_id: int = Depends(get_current_user_id),
):
    """
    PDF 파일 업로드 → static/attachments/{pdf_filename}/ 에 저장.
    """
    pdf_filename = unquote(pdf_filename)
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDFファイルのみアップロードできます。")
    dir_path = _attachments_dir(pdf_filename)
    # 중복 방지: 기존 파일명 유지하되 있으면 suffix 추가
    base_name = Path(file.filename).stem
    ext = ".pdf"
    dest = dir_path / f"{base_name}{ext}"
    while dest.exists():
        dest = dir_path / f"{base_name}_{uuid.uuid4().hex[:8]}{ext}"
    content = await file.read()
    dest.write_bytes(content)
    safe_dir = _safe_doc_dir(pdf_filename)
    url = f"/static/attachments/{safe_dir}/{dest.name}"
    return {"name": dest.name, "url": url}


def _safe_filename(file_name: str) -> str:
    """경로 조작 방지: 파일명만 허용 (슬래시 등 제거)."""
    name = Path(file_name).name
    return name if name and name.endswith(".pdf") else ""


@router.delete("/{pdf_filename}/attachments/delete")
async def delete_attachment(
    pdf_filename: str,
    file_name: str = Query(..., description="삭제할 PDF 파일명"),
    _user_id: int = Depends(get_current_user_id),
):
    """
    첨부 PDF 삭제. file_name 쿼리 파라미터로 파일명 전달.
    """
    pdf_filename = unquote(pdf_filename)
    safe_name = _safe_filename(unquote(file_name))
    if not safe_name:
        raise HTTPException(status_code=400, detail="無効なファイル名です。")
    dir_path = _attachments_dir(pdf_filename)
    target = dir_path / safe_name
    if not target.is_file():
        raise HTTPException(status_code=404, detail="ファイルが見つかりません。")
    target.unlink()
    return {"message": "削除しました。"}
