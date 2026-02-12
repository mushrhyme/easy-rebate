"""
img 폴더 기반 FAISS 벡터 DB 구축 CLI 진입점.

실제 로직은 modules.core.build_faiss_db 에 있습니다.
사용법: python build_faiss_db.py [form_folder]
"""

if __name__ == "__main__":
    import sys
    from modules.core.build_faiss_db import build_faiss_db

    print("🚀 FAISS 벡터 DB 구축 시작\n")
    form_folder = sys.argv[1] if len(sys.argv) > 1 else None
    if form_folder:
        print(f"📁 지정된 폴더: {form_folder}\n")

    build_faiss_db(
        form_folder=form_folder,
        auto_merge=True,
        text_extraction_method="excel",
    )
    print("\n✅ 완료!")
