"""
양식지 타입(form_type) 목록 API - DB에서 동적 조회 / 신규 양식 추가
"""
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database.registry import get_db
from modules.utils.config import get_project_root

router = APIRouter()


class CreateFormTypeRequest(BaseModel):
    """신규 양식지 생성 요청。form_code または display_name のどちらか必須。"""
    form_code: str | None = None  # 指定時はそのコードで作成（従来どおり）
    display_name: str | None = None  # 指定時は次のコードを自動採番し、表示名を form_type_labels に保存


class SavePreviewRequest(BaseModel):
    """미리보기 이미지 저장 요청 (문서 1페이지 이미지 사용)"""
    pdf_filename: str


class UpdateFormTypeLabelRequest(BaseModel):
    """様式コードの表示名変更"""
    display_name: str

# 条件①～⑳ (유니코드 원문자)
_CIRCLED_NUMS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def _form_type_label(code: str) -> str:
    """form_code → 표시 라벨 (01→条件①, 07→条件⑦, 11→型11 등)"""
    if not code or not code.strip():
        return "—"
    try:
        n = int(code.strip())
        if 1 <= n <= 20:
            return f"条件{_CIRCLED_NUMS[n - 1]}"
    except ValueError:
        pass
    return f"型{code}"


@router.get("", response_model=dict)
async def get_form_types(db=Depends(get_db)):
    """
    양식지 타입 목록 조회 (DB 기반).
    - form_field_mappings 의 form_code
    - documents_current, documents_archive 의 form_type
    을 합쳐서 정렬된 목록 반환.
    """
    codes: set[str] = set()
    with db.get_connection() as conn:
        cur = conn.cursor()
        # 1) form_field_mappings (설정된 양식)
        cur.execute(
            "SELECT DISTINCT form_code FROM form_field_mappings WHERE is_active = TRUE ORDER BY form_code"
        )
        for row in cur.fetchall():
            if row[0] and str(row[0]).strip():
                codes.add(str(row[0]).strip())
        # 2) documents (실제 사용 중인 양식)
        cur.execute(
            "SELECT DISTINCT form_type FROM documents_current WHERE form_type IS NOT NULL AND form_type != ''"
        )
        for row in cur.fetchall():
            if row[0] and str(row[0]).strip():
                codes.add(str(row[0]).strip())
        cur.execute(
            "SELECT DISTINCT form_type FROM documents_archive WHERE form_type IS NOT NULL AND form_type != ''"
        )
        for row in cur.fetchall():
            if row[0] and str(row[0]).strip():
                codes.add(str(row[0]).strip())
        # 2자리 zero-pad 정렬 (01, 02, ..., 09, 10, 11)
        def sort_key(c: str) -> tuple:
            try:
                n = int(c)
                return (0, n)
            except ValueError:
                return (1, c)
        sorted_codes = sorted(codes, key=sort_key)
        # 表示名: form_type_labels にあればそれを使用、なければデフォルト (条件① 等)
        labels_map: dict[str, str] = {}
        try:
            cur.execute(
                "SELECT form_code, display_name FROM form_type_labels WHERE form_code = ANY(%s)",
                (list(sorted_codes),),
            )
            for row in cur.fetchall():
                if row[0] and row[1]:
                    labels_map[str(row[0]).strip()] = str(row[1]).strip()
        except Exception:
            pass  # テーブル未作成時はスキップ
    form_types = [
        {"value": c, "label": labels_map.get(c) or _form_type_label(c)}
        for c in sorted_codes
    ]
    return {"form_types": form_types}


# form 01 기준 기본 매핑 (신규 양식 생성 시 복사)
_DEFAULT_MAPPINGS = [
    ("customer", "得意先名"),
    ("customer_code", "得意先CD"),
    ("management_id", "請求伝票番号"),
    ("summary", "備考"),
    ("tax", "消費税率"),
]


@router.patch("/{form_code}/label", response_model=dict)
async def update_form_type_label(
    form_code: str,
    body: UpdateFormTypeLabelRequest,
    db=Depends(get_db),
):
    """
    様式コードの表示名を設定・更新（基準管理）。
    UIで「01」「02」などを任意の名前に変更したときに使用。
    """
    code = form_code.strip()
    if not code or len(code) > 10:
        raise HTTPException(status_code=400, detail="form_code must be 1-10 characters (e.g. 01, 02)")
    display_name = (body.display_name or "").strip()
    if not display_name or len(display_name) > 200:
        raise HTTPException(status_code=400, detail="display_name must be 1-200 characters")
    try:
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO form_type_labels (form_code, display_name, updated_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (form_code) DO UPDATE
                SET display_name = EXCLUDED.display_name, updated_at = CURRENT_TIMESTAMP
                """,
                (code, display_name),
            )
            conn.commit()
        return {"form_code": code, "display_name": display_name, "message": "Label updated"}
    except Exception as e:
        if "form_type_labels" in str(e).lower() and "does not exist" in str(e).lower():
            raise HTTPException(
                status_code=503,
                detail="form_type_labels テーブルがありません。マイグレーション database/migrations/20260212_form_type_labels.sql を実行してください。",
            ) from e
        raise HTTPException(status_code=500, detail=str(e)) from e


def _next_form_code(cur) -> str:
    """既存の form_code を集めて次の番号を返す（01, 02, ... 09, 10, 11）。"""
    codes: set[str] = set()
    for table, col in [
        ("form_field_mappings", "form_code"),
        ("documents_current", "form_type"),
        ("documents_archive", "form_type"),
    ]:
        try:
            cur.execute(f"SELECT DISTINCT {col} FROM {table} WHERE {col} IS NOT NULL AND {col} != ''")
            for row in cur.fetchall():
                if row[0] and str(row[0]).strip():
                    codes.add(str(row[0]).strip())
        except Exception:
            pass
    try:
        cur.execute("SELECT form_code FROM form_type_labels")
        for row in cur.fetchall():
            if row[0] and str(row[0]).strip():
                codes.add(str(row[0]).strip())
    except Exception:
        pass
    max_n = 0
    for c in codes:
        try:
            n = int(c)
            if n > max_n:
                max_n = n
        except ValueError:
            pass
    next_n = max_n + 1
    return f"{next_n:02d}" if next_n < 100 else str(next_n)


@router.post("", response_model=dict)
async def create_form_type(body: CreateFormTypeRequest, db=Depends(get_db)):
    """
    신규 양식지 생성 (form_field_mappings에 기본 매핑 추가).
    - display_name のみ指定: 次の form_code を自動採番し、form_type_labels に表示名を保存。
    - form_code 指定: 従来どおりそのコードで作成（display_name もあれば form_type_labels に保存）。
    """
    raw_code = (body.form_code or "").strip()
    raw_display = (body.display_name or "").strip()
    if not raw_code and not raw_display:
        raise HTTPException(
            status_code=400,
            detail="form_code or display_name is required (e.g. display_name='우편물様式' for auto code)",
        )
    if raw_display and len(raw_display) > 200:
        raise HTTPException(status_code=400, detail="display_name must be at most 200 characters")

    with db.get_connection() as conn:
        cur = conn.cursor()
        if raw_code:
            code = raw_code
            if len(code) > 10:
                raise HTTPException(status_code=400, detail="form_code must be at most 10 characters")
        else:
            code = _next_form_code(cur)

        cur.execute(
            "SELECT 1 FROM form_field_mappings WHERE form_code = %s LIMIT 1",
            (code,),
        )
        if cur.fetchone():
            raise HTTPException(status_code=409, detail=f"form_code {code} already exists")

        for logical_key, physical_key in _DEFAULT_MAPPINGS:
            cur.execute(
                """
                INSERT INTO form_field_mappings (form_code, logical_key, physical_key, is_active)
                VALUES (%s, %s, %s, TRUE)
                ON CONFLICT (form_code, logical_key) DO NOTHING
                """,
                (code, logical_key, physical_key),
            )

        display_name = raw_display or _form_type_label(code)
        try:
            cur.execute(
                """
                INSERT INTO form_type_labels (form_code, display_name, updated_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (form_code) DO UPDATE
                SET display_name = EXCLUDED.display_name, updated_at = CURRENT_TIMESTAMP
                """,
                (code, display_name),
            )
        except Exception:
            pass  # テーブルが無い場合はスキップ

        conn.commit()

    return {
        "form_code": code,
        "display_name": display_name,
        "message": "Form type created",
    }


@router.post("/{form_code}/preview-image", response_model=dict)
async def save_form_preview_image(
    form_code: str,
    body: SavePreviewRequest,
    db=Depends(get_db)
):
    """
    양식지 미리보기 이미지 저장.
    지정 문서의 1페이지 이미지를 frontend/public/images/form_XX.png 로 복사.
    """
    code = form_code.strip()
    if not code or len(code) > 10:
        raise HTTPException(status_code=400, detail="form_code must be 1-10 characters")
    image_path = db.get_page_image_path(body.pdf_filename, 1)
    if not image_path:
        raise HTTPException(
            status_code=404,
            detail=f"1ページ目の画像が見つかりません: {body.pdf_filename}"
        )
    root = get_project_root()
    src_path = root / image_path if not Path(image_path).is_absolute() else Path(image_path)
    if not src_path.exists():
        raise HTTPException(status_code=404, detail=f"画像ファイルが存在しません: {image_path}")
    dest_dir = root / "frontend" / "public" / "images"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"form_{code}.png"
    try:
        from PIL import Image
        img = Image.open(src_path)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(dest_path, "PNG")
    except Exception as e:
        import shutil
        try:
            shutil.copy2(src_path, dest_path)
        except Exception as e2:
            raise HTTPException(status_code=500, detail=f"画像保存失敗: {e2}") from e
    return {"form_code": code, "preview_path": str(dest_path.relative_to(root))}
