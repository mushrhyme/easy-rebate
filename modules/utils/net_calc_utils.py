"""
양식지별 NET 계산 공통 유틸.

규칙:
- 01: 仕切 - (条件 + 条件2), 단 数量単位=CS 이면 仕切 - ((条件 + 条件2) / 入数)
- 02: 仕切 - (条件 + 条件2)
- 03: 仕切 - (条件 + 条件2) 우선, 없으면 仕切 - 単価
- 04: 仕切 - (未収条件 + 未収条件2)
- 05: 仕切 - ((条件 + 条件2) / 入数)
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, TypedDict, Literal


class NetCalcResult(TypedDict):
    net: Optional[float]  # float|None; 예: 1840.5
    base: Optional[float]  # float|None; 예: 차감 기준값
    source: Optional[Literal["cond", "tanka", "mishu"]]  # str|None; 예: "cond"


def _parse_num(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        try:
            return float(v)
        except Exception:
            return None
    s = str(v).strip()
    if not s:
        return None
    s = s.replace("円", "").replace("¥", "").replace("￥", "").strip()  # string; 예: "3,700円" -> "3,700"
    s = s.replace("\uFF0E", ".").replace("\u00B7", ".")  # ．, · -> .
    s = re.sub(r"(\d+):(\d{2,4})", r"\1\2", s)  # string; 예: "1:608" -> "1608"
    if "." not in s and re.match(r"^\d+,\d{1,2}$", s):
        s = s.replace(",", ".")  # string; 예: "39,2" -> "39.2"
    s = s.replace(",", "")
    try:
        return float(s)
    except Exception:
        pass
    s2 = re.sub(r"\s+", ".", s)
    try:
        return float(s2)
    except Exception:
        pass
    s3 = re.sub(r"\s+", "", s)
    try:
        return float(s3)
    except Exception:
        return None


def _sum_nullable(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None and b is None:
        return None
    return (a or 0.0) + (b or 0.0)


def _normalize_form_type(form_type: Optional[str]) -> str:
    return str(form_type or "").strip().lstrip("0")


def _normalize_unit_to_cs(v: Any) -> str:
    s = str(v or "").strip()
    s = s.replace("\uFF23", "C").replace("\uFF33", "S")  # 全角ＣＳ -> CS
    return s.upper()


def calc_net_by_form(item_data: Dict[str, Any], form_type: Optional[str]) -> NetCalcResult:
    shikiri = _parse_num(item_data.get("仕切"))
    if shikiri is None:
        return {"net": None, "base": None, "source": None}

    ft = _normalize_form_type(form_type)
    cond1 = _parse_num(item_data.get("条件"))
    cond2 = _parse_num(item_data.get("条件2"))
    cond_sum = _sum_nullable(cond1, cond2)  # float|None; 예: 126 + 29

    if ft == "1":
        if cond_sum is None:
            return {"net": None, "base": None, "source": "cond"}
        unit_norm = _normalize_unit_to_cs(item_data.get("数量単位"))
        irisu = _parse_num(item_data.get("入数"))
        base = cond_sum / irisu if unit_norm == "CS" and irisu and irisu > 0 else cond_sum
        return {"net": shikiri - base, "base": base, "source": "cond"}

    if ft == "2":
        if cond_sum is None:
            return {"net": None, "base": None, "source": "cond"}
        return {"net": shikiri - cond_sum, "base": cond_sum, "source": "cond"}

    if ft == "3":
        tanka = _parse_num(item_data.get("単価"))
        has_cond = cond_sum is not None
        base = cond_sum if has_cond else tanka
        if base is None:
            return {"net": None, "base": None, "source": None}
        return {"net": shikiri - base, "base": base, "source": "cond" if has_cond else "tanka"}

    if ft == "4":
        misu1 = _parse_num(item_data.get("未収条件"))
        misu2 = _parse_num(item_data.get("未収条件2"))
        base = _sum_nullable(misu1, misu2)
        if base is None:
            return {"net": None, "base": None, "source": "mishu"}
        return {"net": shikiri - base, "base": base, "source": "mishu"}

    if ft == "5":
        irisu = _parse_num(item_data.get("入数"))
        if cond_sum is None or irisu is None or irisu <= 0:
            return {"net": None, "base": None, "source": "cond"}
        base = cond_sum / irisu
        return {"net": shikiri - base, "base": base, "source": "cond"}

    return {"net": None, "base": None, "source": None}
