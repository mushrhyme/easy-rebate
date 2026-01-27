# 사용하지 않는 파일 정리 요약

GitHub 업로드 전 사용하지 않는 파일을 정리했습니다.

## ✅ 삭제 완료

### Python
| 파일 | 비고 |
|------|------|
| `backend/api/dependencies.py` | 어디서도 import 안 됨 |
| `modules/core/registry.py` | `database/registry` 사용 중 |
| `modules/utils/aggregation_utils.py` | 미사용 |
| `modules/utils/merge_utils.py` | 미사용 |
| `modules/utils/session_utils.py` | 미사용 |
| `modules/utils/openai_utils.py` | 미사용 |
| `modules/utils/json_utils.py` | 미사용 |
| `modules/utils/upstage_ocr.py` | `upstage_extractor`에 OCR 로직 있음 |
| `modules/ui/` 전체 | images, README 포함, import 없음 |

### Frontend
| 파일 | 비고 |
|------|------|
| `frontend/src/components/Query/YearMonthTree.tsx` | 미사용 (App에 인라인 목록 사용) |
| `frontend/src/components/Query/YearMonthTree.css` | 위와 함께 삭제 |
| `frontend/src/hooks/useDocuments.ts` | 미사용 (`documentsApi` 직접 사용) |

### 기타
| 파일 | 비고 |
|------|------|
| `form_01.png` ~ `form_05.png` (프로젝트 루트) | `frontend/public/images/`와 중복 |

---

## ⚠️ 삭제하지 않은 것 (선택 정리)

### Prompts (현재 config 사용: `rag_with_example_v3.txt`, `prompt_v2.txt`)
- `prompts/prompt_v1.txt`
- `prompts/rag_with_example_v1.txt`, `v2.txt`, `v4.txt`
- `prompts/rag_zero_shot_v1.txt`  
→ 실험/버전 관리용으로 보관해 두었습니다. 필요 없으면 수동 삭제.

### 스크립트 (앱에서 import 안 함, 수동 실행용)
- `check_key_order.py`
- `build_faiss_db.py`
- `database/check_missing_foreign_keys.py`
- `database/verify_schema.py`  
→ 운영/점검용이므로 유지.

### npm
- `react-router-dom`: 제거함. `frontend`에서 `npm install` 다시 실행하면 lockfile 반영됨.

---

## 참고

- `frontend/README.md`에서 `useDocuments`, `YearMonthTree` 관련 설명을 수정했습니다.
- `.gitignore`에 `debug2/` 포함. 이 디렉터리도 로컬 디버그용으로 사용하지 않으면 삭제해도 됩니다.
