"""
RAG/임베딩 관련 패키지 버전 확인 스크립트.
다른 PC와 비교 시: python scripts/check_package_versions.py
"""
import sys


def get_version(module_name: str, attr: str = "__version__") -> str:
    try:
        m = __import__(module_name)
        return getattr(m, attr, "?")
    except ImportError:
        return "(미설치)"


def main():
    versions = []
    # RAG/임베딩/DB 관련
    packages = [
        ("numpy", "numpy"),
        ("torch", "torch"),
        ("sentence_transformers", "sentence_transformers"),
        ("faiss", "faiss"),
        ("psycopg2", "psycopg2"),
        ("openai", "openai"),
    ]
    for pkg, import_name in packages:
        versions.append(f"{pkg}: {get_version(import_name)}")

    # pgvector는 별도 (패키지명이 다를 수 있음)
    try:
        import pgvector
        versions.append(f"pgvector: {get_version('pgvector')}")
    except ImportError:
        versions.append("pgvector: (미설치)")

    # Python
    versions.append(f"Python: {sys.version.split()[0]}")

    out = "\n".join(versions)
    print(out)
    return out


if __name__ == "__main__":
    main()
