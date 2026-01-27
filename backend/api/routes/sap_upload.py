"""
SAP 업로드 엑셀 파일 생성 API
"""
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from io import BytesIO
import pandas as pd
from openpyxl import load_workbook, Workbook
from openpyxl.utils import get_column_letter, column_index_from_string
from openpyxl.styles import Font, Alignment
import json

from database.registry import get_db

router = APIRouter()


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
                    i.customer,
                    i.product_name,
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


def process_item_for_sap(item: Dict[str, Any], form_type: Optional[str]) -> Dict[str, Any]:
    """
    아이템 데이터를 SAP 양식에 맞게 가공
    
    Args:
        item: 아이템 데이터 (item_data 포함)
        form_type: 양식지 종류 (01~05)
    
    Returns:
        SAP 양식에 맞게 가공된 데이터 (열별 값)
    """
    item_data = item.get('item_data', {})
    if isinstance(item_data, str):
        try:
            item_data = json.loads(item_data)
        except:
            item_data = {}
    
    form_type = form_type or '01'
    
    result = {
        'K': '',  # 得意先 관련
        'L': '',  # 商品名
        'P': '',  # ケース数量
        'T': '',  # 数量 관련
        'Z': '',  # 条件 관련
        'AD': '', # 単価
        'AL': '', # 金額 관련
    }
    
    # [K열] - 양식별 로직
    if form_type == '01':
        # 01: 得意先名 + " " + 得意先コード
        得意先名 = item_data.get('得意先名', '') or item.get('customer', '')
        得意先コード = item_data.get('得意先コード', '')
        result['K'] = f"{得意先名} {得意先コード}".strip()
    elif form_type == '02':
        # 02: 得意先様
        result['K'] = item_data.get('得意先様', '') or item.get('customer', '')
    elif form_type == '03':
        # 03: 得意先名
        result['K'] = item_data.get('得意先名', '') or item.get('customer', '')
    elif form_type in ['04', '05']:
        # 04, 05: 得意先
        result['K'] = item_data.get('得意先', '') or item.get('customer', '')
    
    # [L열] - 모든 양식: 商品名
    result['L'] = item_data.get('商品名', '') or item.get('product_name', '')
    
    # [P열] - 03만: ケース数量
    if form_type == '03':
        result['P'] = item_data.get('ケース数量', '')
    
    # [T열] - 양식별 로직
    if form_type == '01':
        # 01: IF 数量単位="個" → 数量, IF 数量単位="CS" → ケース入数*数量
        数量単位 = item_data.get('数量単位', '')
        数量 = item_data.get('数量', '')
        if 数量単位 == '個':
            result['T'] = 数量
        elif 数量単位 == 'CS':
            ケース入数 = item_data.get('ケース入数', 0) or 0
            try:
                result['T'] = float(ケース入数) * float(数量) if 数量 else ''
            except:
                result['T'] = ''
    elif form_type == '02':
        # 02: 取引数量合計（総数:内数）
        result['T'] = item_data.get('取引数量合計（総数:内数）', '')
    elif form_type == '03':
        # 03: バラ数量
        result['T'] = item_data.get('バラ数量', '')
    elif form_type == '04':
        # 04: 対象数量又は金額
        # '個' 등의 문자를 제거하고 숫자만 추출하여 표시
        import re
        t_value = item_data.get('対象数量又は金額', '')
        if isinstance(t_value, str):
            numbers = re.findall(r'\d+', t_value.replace(',', ''))
            result['T'] = ''.join(numbers) if numbers else ''
        else:
            result['T'] = t_value
    
    # [Z열] - 양식별 로직
    if form_type == '01':
        # 01: IF 条件区分="個" → 条件, IF 条件区分="CS" → 金額/ケース入数*数量
        条件区分 = item_data.get('条件区分', '')
        if 条件区分 == '個':
            result['Z'] = item_data.get('条件', '')
        elif 条件区分 == 'CS':
            金額 = item_data.get('金額', 0) or 0
            ケース入数 = item_data.get('ケース入数', 0) or 0
            数量 = item_data.get('数量', 0) or 0
            try:
                if ケース入数 and 数量:
                    result['Z'] = float(金額) / (float(ケース入数) * float(数量))
                else:
                    result['Z'] = ''
            except:
                result['Z'] = ''
    elif form_type == '03':
        # 03: 条件+条件小数部*0.01
        条件 = item_data.get('条件', 0) or 0
        条件小数部 = item_data.get('条件小数部', 0) or 0
        try:
            result['Z'] = float(条件) + float(条件小数部) * 0.01
        except:
            result['Z'] = ''
    elif form_type == '04':
        # 04: 未収条件+未収条件小数部*0.01
        未収条件 = item_data.get('未収条件', 0) or 0
        未収条件小数部 = item_data.get('未収条件小数部', 0) or 0
        try:
            result['Z'] = float(未収条件) + float(未収条件小数部) * 0.01
        except:
            result['Z'] = ''
    
    # [AD열] - 03만: 単価+単価小数部*0.01
    if form_type == '03':
        単価 = item_data.get('単価', 0) or 0
        単価小数部 = item_data.get('単価小数部', 0) or 0
        try:
            result['AD'] = float(単価) + float(単価小数部) * 0.01
        except:
            result['AD'] = ''
    
    # [AL열] - 양식별 로직
    if form_type == '01':
        # 01: 金額
        result['AL'] = item_data.get('金額', '')
    elif form_type == '02':
        # 02: リベート金額（税別）
        result['AL'] = item_data.get('リベート金額（税別）', '')
    elif form_type == '03':
        # 03: 請求金額
        result['AL'] = item_data.get('請求金額', '')
    elif form_type == '04':
        # 04: 金額
        result['AL'] = item_data.get('金額', '')
    elif form_type == '05':
        # 05: 請求合計額
        result['AL'] = item_data.get('請求合計額', '')
    
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
    
    # 데이터 행 생성
    row_num = data_start_row
    for item in items:
        form_type = item.get('form_type', '01')
        processed = process_item_for_sap(item, form_type)
        
        # 필요한 열에 값 설정 (나머지는 자동으로 공란)
        # K열
        if processed['K']:
            ws[f'K{row_num}'] = processed['K']
        # L열
        if processed['L']:
            ws[f'L{row_num}'] = processed['L']
        # P열
        if processed['P']:
            ws[f'P{row_num}'] = processed['P']
        # T열
        if processed['T']:
            ws[f'T{row_num}'] = processed['T']
        # Z열
        if processed['Z']:
            ws[f'Z{row_num}'] = processed['Z']
        # AD열
        if processed['AD']:
            ws[f'AD{row_num}'] = processed['AD']
        # AL열
        if processed['AL']:
            ws[f'AL{row_num}'] = processed['AL']
        
        # 엑셀 수식 추가 (항상 추가)
        # [U열] =P3*N3 + R3*O3 + T3
        ws[f'U{row_num}'] = f'=P{row_num}*N{row_num} + R{row_num}*O{row_num} + T{row_num}'
        
        # [V열] =U3 / N3
        ws[f'V{row_num}'] = f'=U{row_num} / N{row_num}'
        
        # [AF열] =Z3 + AB3/O3 + AD3/N3
        ws[f'AF{row_num}'] = f'=Z{row_num} + AB{row_num}/O{row_num} + AD{row_num}/N{row_num}'
        
        # [AG열] =AA3 + AC3/O3 + AE3/N3
        ws[f'AG{row_num}'] = f'=AA{row_num} + AC{row_num}/O{row_num} + AE{row_num}/N{row_num}'
        
        # [AH열] =X3 - AF3 - AG3
        ws[f'AH{row_num}'] = f'=X{row_num} - AF{row_num} - AG{row_num}'
        
        # [AI열] =AF3 * U3
        ws[f'AI{row_num}'] = f'=AF{row_num} * U{row_num}'
        
        # [AJ열] =AG3 * U3
        ws[f'AJ{row_num}'] = f'=AG{row_num} * U{row_num}'
        
        # [AK열] =AL3 - AJ3 - AI3
        ws[f'AK{row_num}'] = f'=AL{row_num} - AJ{row_num} - AI{row_num}'
        
        # [AM열] =AH3 / 0.85
        ws[f'AM{row_num}'] = f'=AH{row_num} / 0.85'
        
        # [AP열] =AH3 - AM3*AN3*0.01 - AM3*AO3*0.01
        ws[f'AP{row_num}'] = f'=AH{row_num} - AM{row_num}*AN{row_num}*0.01 - AM{row_num}*AO{row_num}*0.01'
        
        # [AT열] =X3 - AP3
        ws[f'AT{row_num}'] = f'=X{row_num} - AP{row_num}'
        
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
        
        # 처음 50개 아이템만 미리보기
        preview_items = items[:50]
        preview_data = []
        
        for item in preview_items:
            form_type = item.get('form_type', '01')
            processed = process_item_for_sap(item, form_type)
            
            # 모든 컬럼에 대한 데이터 생성
            row_data: Dict[str, Any] = {
                'pdf_filename': item.get('pdf_filename', ''),
                'page_number': item.get('page_number', 0),
                'form_type': form_type,
            }
            
            # A~BB까지 모든 열에 대한 값 설정
            all_columns = get_column_letters_a_to_bb()
            for col_letter in all_columns:
                # 필요한 열만 값 설정
                if col_letter == 'K':
                    row_data[col_letter] = processed['K']
                elif col_letter == 'L':
                    row_data[col_letter] = processed['L']
                elif col_letter == 'P':
                    row_data[col_letter] = processed['P']
                elif col_letter == 'T':
                    row_data[col_letter] = processed['T']
                elif col_letter == 'Z':
                    row_data[col_letter] = processed['Z']
                elif col_letter == 'AD':
                    row_data[col_letter] = processed['AD']
                elif col_letter == 'AL':
                    row_data[col_letter] = processed['AL']
                else:
                    # 나머지는 공란
                    row_data[col_letter] = ''
            
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
