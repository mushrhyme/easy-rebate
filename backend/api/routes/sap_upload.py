"""
SAP 업로드 엑셀 파일 생성 API
- 데이터 입력/수식은 data/sap_upload_formulas.json 설정을 읽어 적용 (단일 소스)
"""
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from io import BytesIO
import re
import pandas as pd
from openpyxl import load_workbook, Workbook
from openpyxl.utils import get_column_letter, column_index_from_string
from openpyxl.styles import Font, Alignment
import json

from database.registry import get_db

router = APIRouter()


# ---------- 설정 기반 규칙 해석 (rule → 값) ----------
# 필드별 대체 키 (예: 得意先名 없으면 得意先 사용)
_FIELD_FALLBACK = {"得意先名": "得意先"}


def _safe_eval_expr(expr: str, item_data: Dict[str, Any]) -> Any:
    """
    item_data 필드명만 사용하는 수식 안전 계산.
    예: "条件+条件小数部*0.01" → item_data["条件"] + item_data["条件小数部"]*0.01
    """
    if not expr or not expr.strip():
        return ""
    expr = expr.strip()
    tokens = re.findall(r"[^\d\s\+\-\*\/\(\)\.\,\=\>\<\'\"]+", expr)
    locals_map = {}
    for t in set(tokens):
        if t in ("and", "or", "not", "True", "False"):
            continue
        v = item_data.get(t)
        if v is None or v == "" and t in _FIELD_FALLBACK:
            v = item_data.get(_FIELD_FALLBACK[t])
        if v is None or v == "":
            v = 0
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = str(v) if v else ""
        locals_map[t] = v
    try:
        work = expr
        for k, v in sorted(locals_map.items(), key=lambda x: -len(x[0])):
            if isinstance(v, str):
                work = work.replace(k, repr(v))
            else:
                work = work.replace(k, str(v))
        return eval(work)
    except Exception:
        return ""


def _apply_data_rule(rule_spec: Any, item_data: Dict[str, Any]) -> Any:
    """
    설정의 rule 한 건을 item_data에 적용해 값 반환.
    rule_spec: 문자열(필드명) | {"field": "필드명"} | {"cond": [...]} | {"expr": "수식"}
    """
    if rule_spec is None:
        return ""
    if isinstance(rule_spec, str):
        return item_data.get(rule_spec, "") or ""
    if not isinstance(rule_spec, dict):
        return ""
    # {"field": "필드명"}
    if "field" in rule_spec:
        return item_data.get(rule_spec["field"], "") or ""
    # {"field_digits": "필드명"} → 필드값에서 숫자만 추출
    if "field_digits" in rule_spec:
        val = item_data.get(rule_spec["field_digits"], "") or ""
        if isinstance(val, str):
            numbers = re.findall(r"\d+", val.replace(",", ""))
            return "".join(numbers) if numbers else ""
        return str(val) if val else ""
    # {"cond": [ {"if_field":"A", "if_eq":"個", "then_field":"B"} | {"then_expr":"..."} }, ...]}
    if "cond" in rule_spec:
        for c in rule_spec["cond"]:
            if_field = c.get("if_field")
            if_eq = c.get("if_eq")
            if if_field is None:
                continue
            if str(item_data.get(if_field, "")) != str(if_eq):
                continue
            if "then_field" in c:
                return item_data.get(c["then_field"], "") or ""
            if "then_expr" in c:
                return _safe_eval_expr(c["then_expr"], item_data)
        return ""
    # {"expr": "수식"}
    if "expr" in rule_spec:
        return _safe_eval_expr(rule_spec["expr"], item_data)
    return ""


def _get_rule_from_by_form(by_form_value: Any) -> Any:
    """byForm[form] 값에서 실행용 rule만 추출 (문자열이면 field 규칙으로 취급)"""
    if by_form_value is None:
        return None
    if isinstance(by_form_value, str):
        return {"field": by_form_value} if by_form_value.strip() else None
    if isinstance(by_form_value, dict) and "rule" in by_form_value:
        return by_form_value["rule"]
    if isinstance(by_form_value, dict) and (
        "field" in by_form_value or "field_digits" in by_form_value
        or "cond" in by_form_value or "expr" in by_form_value
    ):
        return by_form_value
    return None


def get_all_items_current(db) -> List[Dict[str, Any]]:
    """
    items_current 테이블에서 모든 아이템 조회
    ※ page_data_current.page_role = 'detail' 인 건만 대상
    
    Returns:
        모든 아이템 리스트 (pdf_filename, page_number, item_data 포함)
    """
    try:
        with db.get_connection() as conn:
            from psycopg2.extras import RealDictCursor
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT 
                    i.item_id,
                    i.pdf_filename,
                    i.page_number,
                    i.item_order,
                    i.item_data::text as item_data,
                    d.form_type
                FROM items_current i
                LEFT JOIN documents_current d 
                    ON i.pdf_filename = d.pdf_filename
                JOIN page_data_current p
                    ON i.pdf_filename = p.pdf_filename
                   AND i.page_number = p.page_number
                WHERE p.page_role = 'detail'
                ORDER BY i.pdf_filename, i.page_number, i.item_order
            """)
            
            rows = cursor.fetchall()
            result = []
            for row in rows:
                item_dict = dict(row)
                # item_data가 문자열이면 JSON 파싱
                if isinstance(item_dict.get('item_data'), str):
                    try:
                        item_dict['item_data'] = json.loads(item_dict['item_data'])
                    except:
                        item_dict['item_data'] = {}
                result.append(item_dict)
            return result
    except Exception as e:
        print(f"❌ [get_all_items_current] 오류: {e}")
        import traceback
        traceback.print_exc()
        raise


def _load_formulas_config() -> Dict[str, Any]:
    """sap_upload_formulas.json 로드 (없으면 기본값)."""
    path = _get_formulas_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ [formulas config] 읽기 오류: {e}")
    return _default_formulas()


def process_item_for_sap(
    item: Dict[str, Any],
    form_type: Optional[str],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    아이템 데이터를 SAP 양식에 맞게 가공.
    config(sap_upload_formulas.json)의 dataInputColumns 규칙을 적용.
    """
    item_data = item.get('item_data', {})
    if isinstance(item_data, str):
        try:
            item_data = json.loads(item_data)
        except Exception:
            item_data = {}
    if not isinstance(item_data, dict):
        item_data = {}

    form_type = (form_type or "01").strip()
    if form_type not in ("01", "02", "03", "04", "05"):
        form_type = "01"

    if config is None:
        config = _load_formulas_config()

    data_columns = config.get("dataInputColumns") or []
    result = {}
    for col_spec in data_columns:
        col = col_spec.get("column")
        if not col:
            continue
        by_form = col_spec.get("byForm") or {}
        raw = by_form.get(form_type)
        rule = _get_rule_from_by_form(raw)
        if rule is None:
            result[col] = ""
            continue
        val = _apply_data_rule(rule, item_data)
        if val is None:
            val = ""
        result[col] = val

    return result


def get_column_letters_a_to_bb() -> List[str]:
    """
    A~BB열까지 모든 열 문자 리스트 생성
    
    Returns:
        ['A', 'B', ..., 'Z', 'AA', 'AB', ..., 'AZ', 'BA', 'BB']
    """
    columns = []
    # A~BB까지 총 54개 열 (A=1, Z=26, AA=27, AZ=52, BA=53, BB=54)
    for i in range(1, 55):  # 1부터 54까지
        columns.append(get_column_letter(i))
    return columns


def create_sap_excel(items: List[Dict[str, Any]], template_path: Optional[str] = None) -> BytesIO:
    """
    SAP 업로드용 엑셀 파일 생성
    
    Args:
        items: 모든 아이템 리스트
        template_path: 템플릿 파일 경로 (선택사항)
    
    Returns:
        엑셀 파일 바이트 스트림
    """
    from pathlib import Path
    
    # 템플릿 파일이 있으면 로드, 없으면 새로 생성
    if template_path and Path(template_path).exists():
        wb = load_workbook(template_path)
        ws = wb.active
        # 첫 행(1행)은 컬럼명이므로 유지
        # 기존 데이터 행 삭제 (2행부터 삭제)
        if ws.max_row >= 2:
            ws.delete_rows(2, ws.max_row - 1)
        data_start_row = 2  # 2행부터 데이터 시작
    else:
        # 새 워크북 생성 (템플릿이 없으면 컬럼명도 없으므로 경고)
        # 실제로는 템플릿 파일을 사용하는 것이 권장됨
        wb = Workbook()
        ws = wb.active
        ws.title = "SAP Upload"
        # 템플릿이 없으면 첫 행에 컬럼명이 없으므로
        # 2행부터 데이터 시작 (1행은 비어있음)
        data_start_row = 2
        # A~BB열까지 모든 열이 존재하도록 보장 (최소한 한 행이라도 있어야 열이 생성됨)
        # 첫 번째 데이터 행을 미리 생성하여 모든 열이 존재하도록 함
        all_columns = get_column_letters_a_to_bb()
        for col_letter in all_columns:
            ws[f'{col_letter}{data_start_row}'] = ''
    
    config = _load_formulas_config()
    data_columns = [c["column"] for c in (config.get("dataInputColumns") or [])]
    formula_columns = config.get("excelFormulaColumns") or []

    # 수식 템플릿에서 행 번호 치환 (3 → 실제 row_num). 예: =P3*N3 → =P{row}*N{row}
    def formula_for_row(formula_tpl: str, row_num: int) -> str:
        if not formula_tpl or not str(formula_tpl).strip().startswith("="):
            return formula_tpl
        return re.sub(r"([A-Z]+)\d+", lambda m: m.group(1) + str(row_num), formula_tpl)

    row_num = data_start_row
    for item in items:
        form_type = item.get("form_type", "01")
        processed = process_item_for_sap(item, form_type, config)

        for col in data_columns:
            val = processed.get(col)
            if val is not None and val != "":
                try:
                    ws[f"{col}{row_num}"] = val
                except Exception:
                    pass

        for fc in formula_columns:
            col = fc.get("column")
            formula_tpl = fc.get("formula")
            if col and formula_tpl:
                ws[f"{col}{row_num}"] = formula_for_row(formula_tpl, row_num)

        row_num += 1
    
    # 파일을 메모리에 저장
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    return output


@router.get("/preview")
async def preview_sap_excel(
    db=Depends(get_db)
):
    """
    SAP 엑셀 파일 미리보기 (JSON 형식으로 반환)
    
    Returns:
        엑셀 데이터의 미리보기 (처음 50행) + 템플릿의 모든 컬럼명
    """
    try:
        from pathlib import Path
        
        items = get_all_items_current(db)
        
        # 템플릿 파일에서 컬럼명 읽기
        project_root = Path(__file__).parent.parent.parent.parent
        template_path = project_root / "static" / "sap_upload.xlsx"
        
        column_names = []
        if template_path.exists():
            wb = load_workbook(template_path, read_only=True)
            ws = wb.active
            # 첫 행(1행)에서 모든 컬럼명 읽기
            for col_idx in range(1, ws.max_column + 1):
                cell_value = ws.cell(row=1, column=col_idx).value
                if cell_value:
                    column_names.append(str(cell_value))
                else:
                    # 값이 없어도 열은 존재하므로 빈 문자열 추가
                    column_names.append('')
            wb.close()
        else:
            # 템플릿이 없으면 A~BB까지 열 문자로 표시
            all_columns = get_column_letters_a_to_bb()
            column_names = all_columns
        
        if not items:
            return {
                "total_items": 0,
                "preview_rows": [],
                "column_names": column_names,
                "message": "データがありません"
            }
        
        config = _load_formulas_config()
        preview_items = items[:50]
        preview_data = []

        for item in preview_items:
            form_type = item.get("form_type", "01")
            processed = process_item_for_sap(item, form_type, config)

            row_data: Dict[str, Any] = {
                "pdf_filename": item.get("pdf_filename", ""),
                "page_number": item.get("page_number", 0),
                "form_type": form_type,
            }
            all_columns = get_column_letters_a_to_bb()
            for col_letter in all_columns:
                row_data[col_letter] = processed.get(col_letter, "")

            preview_data.append(row_data)
        
        return {
            "total_items": len(items),
            "preview_rows": preview_data,
            "column_names": column_names,
            "message": f"全{len(items)}件のデータがあります（最初の50件を表示）"
        }
    except Exception as e:
        print(f"❌ [preview_sap_excel] 오류: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download")
async def download_sap_excel(
    db=Depends(get_db)
):
    """
    SAP 업로드용 엑셀 파일 다운로드
    
    Returns:
        엑셀 파일 (StreamingResponse)
    """
    try:
        items = get_all_items_current(db)
        
        if not items:
            raise HTTPException(status_code=404, detail="データがありません")
        
        # 템플릿 파일 경로 확인
        from pathlib import Path
        project_root = Path(__file__).parent.parent.parent.parent
        template_path = project_root / "static" / "sap_upload.xlsx"
        
        # 템플릿 파일이 있으면 사용, 없으면 None
        template_file = str(template_path) if template_path.exists() else None
        
        excel_file = create_sap_excel(items, template_file)
        
        # 파일명 생성 (현재 날짜 포함)
        from datetime import datetime
        filename = f"SAP_Upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        return StreamingResponse(
            excel_file,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [download_sap_excel] 오류: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/column-names")
async def get_sap_column_names():
    """
    SAP 업로드 템플릿(sap_upload.xlsx) 1행에서 컬럼명 목록 반환.
    산식 표시 시 실제 컬럼명 표시용.
    """
    from pathlib import Path
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    template_path = project_root / "static" / "sap_upload.xlsx"
    column_names = []
    if template_path.exists():
        wb = load_workbook(template_path, read_only=True)
        ws = wb.active
        for col_idx in range(1, ws.max_column + 1):
            cell_value = ws.cell(row=1, column=col_idx).value
            if cell_value:
                column_names.append(str(cell_value))
            else:
                column_names.append("")
        wb.close()
    else:
        column_names = get_column_letters_a_to_bb()
    return {"column_names": column_names}


# ========== SAP 산식 설정 (양식지별 편집용) ==========
def _get_formulas_path() -> "Path":
    from pathlib import Path
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    data_dir = project_root / "data"
    data_dir.mkdir(exist_ok=True)
    return data_dir / "sap_upload_formulas.json"


def _default_formulas() -> Dict[str, Any]:
    """
    sap_upload.md 기반 기본 산식 (양식지 01~05별).
    byForm 값: 문자열=필드명(field), 객체=rule(field/cond/expr). 백엔드가 이 규칙을 해석해 적용.
    """
    return {
        "dataInputColumns": [
            {"column": "B", "byForm": {"01": {"field": "판매처"}, "02": "", "03": "", "04": "", "05": ""}},
            {"column": "C", "byForm": {"01": {"field": "판매처コード"}, "02": "", "03": "", "04": "", "05": ""}},
            {"column": "D", "byForm": {"01": "", "02": "", "03": "", "04": "", "05": ""}},
            {"column": "I", "byForm": {"01": {"field": "得意先"}, "02": {"field": "得意先"}, "03": {"field": "得意先"}, "04": {"field": "得意先"}, "05": {"field": "得意先"}}},
            {"column": "J", "byForm": {"01": {"field": "得意先"}, "02": {"field": "得意先"}, "03": {"field": "得意先"}, "04": {"field": "得意先"}, "05": {"field": "得意先"}}},
            {
                "column": "K",
                "byForm": {
                    "01": {"expr": "得意先名 + ' ' + 得意先CD"},
                    "02": {"field": "得意先様"},
                    "03": {"field": "得意先名"},
                    "04": {"field": "得意先"},
                    "05": {"field": "得意先"},
                },
            },
            {"column": "L", "byForm": {"01": {"field": "商品名"}, "02": {"field": "商品名"}, "03": {"field": "商品名"}, "04": {"field": "商品名"}, "05": {"field": "商品名"}}},
            {"column": "P", "byForm": {"01": "", "02": "", "03": {"field": "ケース数量"}, "04": "", "05": ""}},
            {
                "column": "T",
                "byForm": {
                    "01": {
                        "cond": [
                            {"if_field": "数量単位", "if_eq": "個", "then_field": "数量"},
                            {"if_field": "数量単位", "if_eq": "CS", "then_expr": "入数*数量"},
                        ]
                    },
                    "02": {"field": "取引数量合計（総数:内数）"},
                    "03": {"field": "バラ数量"},
                    "04": {"field_digits": "対象数量又は金額"},
                    "05": "",
                },
            },
            {
                "column": "Z",
                "byForm": {
                    "01": {
                        "cond": [
                            {"if_field": "条件区分", "if_eq": "個", "then_field": "条件"},
                            {"if_field": "条件区分", "if_eq": "CS", "then_expr": "金額/(入数*数量)"},
                        ]
                    },
                    "02": "",
                    "03": {"expr": "条件+条件小数部*0.01"},
                    "04": {"expr": "未収条件+未収条件小数部*0.01"},
                    "05": "",
                },
            },
            {"column": "AD", "byForm": {"01": "", "02": "", "03": {"expr": "単価+単価小数部*0.01"}, "04": "", "05": ""}},
            {
                "column": "AL",
                "byForm": {
                    "01": {"field": "金額"},
                    "02": {"field": "リベート金額（税別）"},
                    "03": {"field": "請求金額"},
                    "04": {"field": "金額"},
                    "05": {"field": "請求合計額"},
                },
            },
        ],
        "excelFormulaColumns": [
            {"column": "U", "formula": "=P3*N3 + R3*O3 + T3", "description": "P×N + R×O + T"},
            {"column": "V", "formula": "=U3 / N3", "description": "U ÷ N"},
            {"column": "AF", "formula": "=Z3 + AB3/O3 + AD3/N3", "description": "Z + AB/O + AD/N"},
            {"column": "AG", "formula": "=AA3 + AC3/O3 + AE3/N3", "description": "AA + AC/O + AE/N"},
            {"column": "AH", "formula": "=X3 - AF3 - AG3", "description": "X - AF - AG"},
            {"column": "AI", "formula": "=AF3 * U3", "description": "AF × U"},
            {"column": "AJ", "formula": "=AG3 * U3", "description": "AG × U"},
            {"column": "AK", "formula": "=AL3 - AJ3 - AI3", "description": "AL - AJ - AI"},
            {"column": "AM", "formula": "=AH3 / 0.85", "description": "AH ÷ 0.85"},
            {"column": "AP", "formula": "=AH3 - AM3*AN3*0.01 - AM3*AO3*0.01", "description": "AH - AM×AN×0.01 - AM×AO×0.01"},
            {"column": "AT", "formula": "=X3 - AP3", "description": "X - AP"},
        ],
    }


@router.get("/formulas")
async def get_sap_formulas():
    """
    SAP 산식 설정 조회 (양식지 01~05별 데이터 입력, 엑셀 수식).
    파일 없으면 기본값 반환.
    """
    path = _get_formulas_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ [get_sap_formulas] 읽기 오류: {e}")
    return _default_formulas()


@router.put("/formulas")
async def put_sap_formulas(body: Dict[str, Any]):
    """
    SAP 산식 설정 저장 (양식지별 편집 결과).
    """
    path = _get_formulas_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False, indent=2)
        return {"ok": True}
    except Exception as e:
        print(f"❌ [put_sap_formulas] 저장 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))
