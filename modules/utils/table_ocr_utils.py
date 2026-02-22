"""
Azure OCR raw 결과를 표 구조가 복원된 텍스트(TSV)로 변환하는 유틸.

- 벡터 DB 임베딩·RAG 검색·프롬프트에 동일한 "표 복원 OCR" 형식을 쓰기 위해 공통화.
- raw: Azure extract_from_image_raw / extract_from_pdf_page_raw 반환 형식
  (text, pages[], tables[] with cells[rowIndex, columnIndex, content])
"""

from typing import Dict, Any

import pandas as pd

from modules.utils.text_normalizer import normalize_ocr_text


def azure_table_to_dataframe(table: dict) -> pd.DataFrame:
    """Azure 표 한 개를 DataFrame으로 복원 (rowSpan/columnSpan 반영)."""
    cells = table.get("cells") or []
    if not cells:
        return pd.DataFrame()
    max_r = max(c.get("rowIndex", 0) + (c.get("rowSpan") or 1) - 1 for c in cells)
    max_c = max(c.get("columnIndex", 0) + (c.get("columnSpan") or 1) - 1 for c in cells)
    grid = [["" for _ in range(max_c + 1)] for _ in range(max_r + 1)]
    for cell in cells:
        r, c = cell.get("rowIndex", 0), cell.get("columnIndex", 0)
        rs, cs = cell.get("rowSpan") or 1, cell.get("columnSpan") or 1
        content = (cell.get("content") or "").strip()
        for rr in range(r, min(r + rs, len(grid))):
            for cc in range(c, min(c + cs, len(grid[0]))):
                grid[rr][cc] = content
    return pd.DataFrame(grid)


def raw_to_full_text(raw: Dict[str, Any]) -> str:
    """
    Azure raw 결과에서 인식한 전체 문자열만 반환 (표/비표 구분 없이).
    정답지 생성 탭 OCR 표시용 — 사용자가 '인식한 모든 문자열'을 볼 수 있도록.
    """
    if not raw or not isinstance(raw, dict):
        return ""
    text = (raw.get("text") or "").strip()
    if not text and raw.get("pages"):
        text = "\n".join(
            " ".join(w.get("text", "") or w.get("content", "") for w in p.get("words") or [])
            for p in raw["pages"]
        )
    return normalize_ocr_text((text or "").strip(), use_fullwidth=True)


def raw_to_table_restored_text(raw: Dict[str, Any]) -> str:
    """
    Azure raw 결과를 표 복원 텍스트로 변환.

    - tables가 있으면: 각 표를 TSV로 (첫 행=헤더, 이후 데이터 행). LLM이 열 이름(ケース/バラ 등)으로 매핑 가능.
    - tables가 없으면: result['text'] 또는 pages에서 단어 이어붙인 텍스트 반환.
    """
    if not raw or not isinstance(raw, dict):
        return ""

    tables = raw.get("tables") or []
    if not tables:
        text = (raw.get("text") or "").strip()
        if not text and raw.get("pages"):
            text = "\n".join(
                " ".join(w.get("text", "") or w.get("content", "") for w in p.get("words") or [])
                for p in raw["pages"]
            )
        return normalize_ocr_text(text or "", use_fullwidth=True)

    parts = []
    for tbl in tables:
        df = azure_table_to_dataframe(tbl)
        if df.empty:
            continue
        header = "\t".join(str(df.iloc[0, j]) for j in range(len(df.columns)))
        rows = ["\t".join(str(df.iloc[i, j]) for j in range(len(df.columns))) for i in range(1, len(df))]
        parts.append(header + "\n" + "\n".join(rows))
    return normalize_ocr_text("\n\n".join(parts) or "", use_fullwidth=True)
