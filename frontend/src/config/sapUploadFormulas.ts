/**
 * SAP 업로드 양식 컬럼별 산식
 * 단일 소스: 백엔드 GET /api/sap-upload/formulas (또는 static/sap_upload_formulas.json).
 * byForm 값: 문자열(필드명) 또는 { field/cond/expr }. rule은 백엔드가 해석해 적용.
 */

import type { SapFormulasConfig, ByFormValue, DataInputRule } from '@/types'

/** 데이터 미수신 시 UI 크래시 방지용 빈 구조. 실제 내용은 항상 GET 응답 사용 */
export const EMPTY_SAP_FORMULAS: SapFormulasConfig = {
  dataInputColumns: [],
  excelFormulaColumns: [],
}

/** cond 한 건 → "if 필드=값 then 결과" 형태 (여러 건은 " else if "로 연결) */
function condItemToText(
  c: { if_field: string; if_eq: string; then_field?: string; then_expr?: string },
  isFirst: boolean
): string {
  const then = c.then_field ?? c.then_expr ?? ''
  return isFirst ? `if ${c.if_field}=${c.if_eq} then ${then}` : `else if ${c.if_field}=${c.if_eq} then ${then}`
}

/** 분기 텍스트 파싱: "if A=B then C else if D=E then F" → { cond: [...] } (/ 는 쓰지 않음, 수식의 나누기와 구분) */
export function parseCondFromText(
  text: string
): { cond: Array<{ if_field: string; if_eq: string; then_field?: string; then_expr?: string }> } | null {
  const trimmed = text.trim()
  if (!trimmed) return null
  const cond: Array<{ if_field: string; if_eq: string; then_field?: string; then_expr?: string }> = []
  const segments = trimmed.split(/\s+else\s+if\s+/i).map((s) => s.trim()).filter(Boolean)
  for (let i = 0; i < segments.length; i++) {
    let seg = segments[i]
    if (i === 0 && seg.toLowerCase().startsWith('if ')) seg = seg.slice(3).trim()
    const thenIdx = seg.indexOf(' then ')
    if (thenIdx === -1) continue
    const left = seg.slice(0, thenIdx).trim()
    const right = seg.slice(thenIdx + 6).trim()
    const eqIdx = left.indexOf('=')
    if (eqIdx === -1) continue
    const if_field = left.slice(0, eqIdx).trim()
    const if_eq = left.slice(eqIdx + 1).trim()
    if (!if_field || right === '') continue
    const hasOperator = /[*\/+\-]/.test(right)
    if (hasOperator) {
      cond.push({ if_field, if_eq, then_expr: right })
    } else {
      cond.push({ if_field, if_eq, then_field: right })
    }
  }
  return cond.length > 0 ? { cond } : null
}

/** rule 객체 → 짧은 설명 문자열 (표시용) */
export function ruleToShortText(rule: DataInputRule | undefined): string {
  if (!rule) return ''
  if ('field' in rule && rule.field) return `項目: ${rule.field}`
  if ('field_digits' in rule && rule.field_digits) return `項目(数字のみ): ${rule.field_digits}`
  if ('cond' in rule && Array.isArray(rule.cond) && rule.cond.length > 0)
    return rule.cond.map((c, i) => condItemToText(c, i === 0)).join(' ')
  if ('expr' in rule && rule.expr) return rule.expr
  return ''
}

/** byForm 셀 값 → 표시/편집용 문자열 */
export function byFormValueToDisplay(v: ByFormValue): string {
  if (v == null) return ''
  if (typeof v === 'string') return v
  if (v.description?.trim()) return v.description
  if (v.rule) return ruleToShortText(v.rule)
  // 백엔드가 rule 래퍼 없이 { field }, { expr } 등만 내려준 경우
  return ruleToShortText(v as DataInputRule)
}

/** byForm → 표시용 description 목록 (formKeys 순서, 공란 제외). keyToLabel 있으면 번호 대신 디스플레이명 표시 */
export function dataInputToDescriptionLines(
  byForm: Record<string, ByFormValue>,
  formKeys: string[] = Object.keys(byForm).sort(),
  keyToLabel?: Record<string, string>
): string[] {
  return formKeys
    .map((k) => {
      const disp = byFormValueToDisplay(byForm[k])
      const prefix = keyToLabel?.[k] ?? k
      return disp.trim() ? `${prefix}: ${disp}` : ''
    })
    .filter(Boolean)
}
