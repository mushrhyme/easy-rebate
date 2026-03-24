"""

행(item) 단위 PDF 첨부 API — static/attachments/{safe_doc}/items/{item_id}/ 에 저장



권장 URL(구 API와 동일 경로 + 쿼리 item_id):

  GET    /.../attachments/list?item_id=

  POST   /.../attachments/upload?item_id=  (multipart file)

  DELETE /.../attachments/delete?item_id=&file_name=

  POST   /.../attachments/claim-legacy?item_id=



호환: /.../items/{item_id}/attachments/... 경로형도 유지

"""

import re

import uuid

from pathlib import Path

from urllib.parse import unquote



from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Query



from modules.utils.config import get_project_root

from backend.core.auth import get_current_user_id



router = APIRouter()





def _safe_doc_dir(pdf_filename: str) -> str:

    s = re.sub(r"[^\w\-\.]", "_", pdf_filename)

    return s.strip("._") or "default"





def _doc_base_dir(pdf_filename: str) -> Path:

    root = get_project_root()

    base = root / "static" / "attachments"

    base.mkdir(parents=True, exist_ok=True)

    doc_dir = base / _safe_doc_dir(pdf_filename)

    doc_dir.mkdir(parents=True, exist_ok=True)

    return doc_dir





def _item_attachments_dir(pdf_filename: str, item_id: int) -> Path:

    d = _doc_base_dir(pdf_filename) / "items" / str(int(item_id))

    d.mkdir(parents=True, exist_ok=True)

    return d





def _safe_filename(file_name: str) -> str:

    name = Path(file_name).name

    return name if name and name.endswith(".pdf") else ""





def _file_url(safe_dir: str, item_id: int, filename: str) -> str:

    return f"/static/attachments/{safe_dir}/items/{item_id}/{filename}"





def _list_row_attachments_dict(pdf_filename: str, item_id: int) -> dict:

    dir_path = _item_attachments_dir(pdf_filename, item_id)

    safe_dir = _safe_doc_dir(pdf_filename)

    files = []

    for p in dir_path.iterdir():

        if p.is_file() and p.suffix.lower() == ".pdf":

            files.append({"name": p.name, "url": _file_url(safe_dir, item_id, p.name)})

    files.sort(key=lambda x: x["name"])

    return {"files": files}





def _parse_item_ids_csv(item_ids_csv: str) -> list[int]:

    """쿼리 item_ids=1,2,3 → [1, 2, 3]"""

    if not item_ids_csv or not str(item_ids_csv).strip():

        return []

    out: list[int] = []

    for part in str(item_ids_csv).split(","):

        p = part.strip()

        if not p:

            continue

        out.append(int(p))

    return out





def _claim_legacy_dict(pdf_filename: str, item_id: int) -> dict:

    doc_base = _doc_base_dir(pdf_filename)

    dest_dir = _item_attachments_dir(pdf_filename, item_id)

    moved: list[str] = []

    for p in list(doc_base.iterdir()):

        if not p.is_file() or p.suffix.lower() != ".pdf":

            continue

        dest = dest_dir / p.name

        while dest.exists():

            dest = dest_dir / f"{p.stem}_{uuid.uuid4().hex[:8]}.pdf"

        p.rename(dest)

        moved.append(dest.name)

    return {"moved": moved, "count": len(moved)}





async def _do_upload(pdf_filename: str, item_id: int, file: UploadFile) -> dict:

    if not file.filename or not file.filename.lower().endswith(".pdf"):

        raise HTTPException(status_code=400, detail="PDFファイルのみアップロードできます。")

    dir_path = _item_attachments_dir(pdf_filename, item_id)

    base_name = Path(file.filename).stem

    ext = ".pdf"

    dest = dir_path / f"{base_name}{ext}"

    while dest.exists():

        dest = dir_path / f"{base_name}_{uuid.uuid4().hex[:8]}{ext}"

    content = await file.read()

    dest.write_bytes(content)

    safe_dir = _safe_doc_dir(pdf_filename)

    return {"name": dest.name, "url": _file_url(safe_dir, item_id, dest.name)}





def _do_delete(pdf_filename: str, item_id: int, file_name: str) -> dict:

    safe_name = _safe_filename(unquote(file_name))

    if not safe_name:

        raise HTTPException(status_code=400, detail="無効なファイル名です。")

    dir_path = _item_attachments_dir(pdf_filename, item_id)

    target = dir_path / safe_name

    if not target.is_file():

        raise HTTPException(status_code=404, detail="ファイルが見つかりません。")

    target.unlink()

    return {"message": "削除しました。"}





# ----- 레거시(문서 루트 PDF) -----





@router.get("/{pdf_filename}/attachments/legacy-list")

async def list_legacy_root_pdfs(

    pdf_filename: str,

    _user_id: int = Depends(get_current_user_id),

):

    pdf_filename = unquote(pdf_filename)

    doc_base = _doc_base_dir(pdf_filename)

    safe_dir = _safe_doc_dir(pdf_filename)

    files = []

    if not doc_base.is_dir():

        return {"files": files}

    for p in doc_base.iterdir():

        if p.is_file() and p.suffix.lower() == ".pdf":

            files.append({"name": p.name, "url": f"/static/attachments/{safe_dir}/{p.name}"})

    files.sort(key=lambda x: x["name"])

    return {"files": files}





# ----- 쿼리 item_id (구 /attachments/* 패턴) -----





@router.get("/{pdf_filename}/attachments/flags")

async def attachment_flags_by_items(

    pdf_filename: str,

    item_ids: str = Query(default="", description="comma-separated item_id list (e.g. 1,2,3)"),

    _user_id: int = Depends(get_current_user_id),

):

    """페이지 그리드용: 행별 PDF 첨부 유무 일괄 조회."""

    decoded = unquote(pdf_filename)

    ids = _parse_item_ids_csv(item_ids)

    flags: dict[str, bool] = {}

    for iid in ids:

        d = _list_row_attachments_dict(decoded, iid)

        flags[str(iid)] = len(d.get("files") or []) > 0

    return {"flags": flags}





@router.get("/{pdf_filename}/attachments/list")

async def list_attachments_query(

    pdf_filename: str,

    item_id: int = Query(..., description="행 DB id (items.item_id)"),

    _user_id: int = Depends(get_current_user_id),

):

    return _list_row_attachments_dict(unquote(pdf_filename), item_id)





@router.post("/{pdf_filename}/attachments/upload")

async def upload_attachment_query(

    pdf_filename: str,

    item_id: int = Query(..., description="행 DB id"),

    file: UploadFile = File(...),

    _user_id: int = Depends(get_current_user_id),

):

    return await _do_upload(unquote(pdf_filename), item_id, file)





@router.delete("/{pdf_filename}/attachments/delete")

async def delete_attachment_query(

    pdf_filename: str,

    item_id: int = Query(..., description="행 DB id"),

    file_name: str = Query(..., description="삭제할 PDF 파일명"),

    _user_id: int = Depends(get_current_user_id),

):

    return _do_delete(unquote(pdf_filename), item_id, file_name)





@router.post("/{pdf_filename}/attachments/claim-legacy")

async def claim_legacy_query(

    pdf_filename: str,

    item_id: int = Query(..., description="이동 대상 행 item_id"),

    _user_id: int = Depends(get_current_user_id),

):

    return _claim_legacy_dict(unquote(pdf_filename), item_id)





# ----- 경로형 item_id -----





@router.post("/{pdf_filename}/items/{item_id}/attachments/claim-legacy")

async def claim_legacy_path(

    pdf_filename: str,

    item_id: int,

    _user_id: int = Depends(get_current_user_id),

):

    return _claim_legacy_dict(unquote(pdf_filename), item_id)





@router.get("/{pdf_filename}/items/{item_id}/attachments/list")

async def list_attachments_path(

    pdf_filename: str,

    item_id: int,

    _user_id: int = Depends(get_current_user_id),

):

    return _list_row_attachments_dict(unquote(pdf_filename), item_id)





@router.post("/{pdf_filename}/items/{item_id}/attachments/upload")

async def upload_attachment_path(

    pdf_filename: str,

    item_id: int,

    file: UploadFile = File(...),

    _user_id: int = Depends(get_current_user_id),

):

    return await _do_upload(unquote(pdf_filename), item_id, file)





@router.delete("/{pdf_filename}/items/{item_id}/attachments/delete")

async def delete_attachment_path(

    pdf_filename: str,

    item_id: int,

    file_name: str = Query(..., description="삭제할 PDF 파일명"),

    _user_id: int = Depends(get_current_user_id),

):

    return _do_delete(unquote(pdf_filename), item_id, file_name)


