"""
retail_user.csv 기반 담당 슈퍼명 조회 (DB 미사용).

CSV 컬럼: 소매처코드, 소매처명, 담당자ID, 담당자명, ID (ID = users.username)
"""

import csv
from pathlib import Path
from typing import List

from modules.utils.config import get_project_root


def get_super_names_for_username(username: str) -> List[str]:
    """
    retail_user.csv에서 해당 username(ID 열)에 매핑된 소매처명 목록 반환.

    Returns:
        슈퍼명 리스트 (중복 제거)
    """
    path = get_project_root() / "database" / "csv" / "retail_user.csv"
    if not path.exists():
        return []
    username = (username or "").strip()
    if not username:
        return []
    seen: set[str] = set()
    result: List[str] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (row.get("ID") or "").strip() != username:
                    continue
                name = (row.get("소매처명") or "").strip()
                if name and name not in seen:
                    seen.add(name)
                    result.append(name)
    except Exception:
        return []
    return result


def get_all_super_names() -> List[str]:
    """
    retail_user.csv의 소매처명 전체(중복 제거). notepad find_similar_supers와 동일 풀 비교용.
    """
    path = get_project_root() / "database" / "csv" / "retail_user.csv"
    if not path.exists():
        return []
    seen: set[str] = set()
    result: List[str] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = (row.get("소매처명") or "").strip()
                if name and name not in seen:
                    seen.add(name)
                    result.append(name)
    except Exception:
        return []
    return result
