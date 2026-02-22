/**
 * SAP 업로드 양식 컬럼별 산식 (sap_upload.md 기반)
 * API 형식: dataInputColumns(양식지별), excelFormulaColumns
 * byForm 값: 문자열(설명) 또는 { description?, rule? }. rule은 백엔드가 해석해 적용.
 */

import type { SapFormulasConfig, ByFormValue, DataInputRule } from '@/types'

/** API 기본값 (서버에 파일 없을 때 사용) */
export const DEFAULT_SAP_FORMULAS: SapFormulasConfig = {
  dataInputColumns: [
    { column: 'B', byForm: { '01': '판매처', '02': '', '03': '', '04': '', '05': '' } },
    { column: 'C', byForm: { '01': '판매처코드', '02': '', '03': '', '04': '', '05': '' } },
    { column: 'D', byForm: { '01': '', '02': '', '03': '', '04': '', '05': '' } },
    { column: 'I', byForm: { '01': '得意先', '02': '得意先', '03': '得意先', '04': '得意先', '05': '得意先' } },
    { column: 'J', byForm: { '01': '得意先', '02': '得意先', '03': '得意先', '04': '得意先', '05': '得意先' } },
    { column: 'K', byForm: { '01': '得意先', '02': '得意先', '03': '得意先', '04': '得意先', '05': '得意先' } },
    { column: 'L', byForm: { '01': '商品名', '02': '商品名', '03': '商品名', '04': '商品名', '05': '商品名' } },
    { column: 'P', byForm: { '01': '', '02': '', '03': 'ケース数量', '04': '', '05': '' } },
    {
      column: 'T',
      byForm: {
        '01': '数量単位="個" → 数量 / 数量単位="CS" → 入数×数量',
        '02': '取引数量合計（総数:内数）',
        '03': 'バラ数量',
        '04': '対象数量又は金額',
        '05': '',
      },
    },
    {
      column: 'Z',
      byForm: {
        '01': '条件区分="個" → 条件 / 条件区分="CS" → 金額/入数×数量',
        '02': '',
        '03': '条件+条件小数部×0.01',
        '04': '未収条件+未収条件小数部×0.01',
        '05': '',
      },
    },
    { column: 'AD', byForm: { '01': '', '02': '', '03': '単価+単価小数部×0.01', '04': '', '05': '' } },
    {
      column: 'AL',
      byForm: {
        '01': '金額',
        '02': 'リベート金額（税別）',
        '03': '請求金額',
        '04': '金額',
        '05': '請求合計額',
      },
    },
  ],
  excelFormulaColumns: [
    { column: 'U', formula: '=P3*N3 + R3*O3 + T3', description: 'P×N + R×O + T' },
    { column: 'V', formula: '=U3 / N3', description: 'U ÷ N' },
    { column: 'AF', formula: '=Z3 + AB3/O3 + AD3/N3', description: 'Z + AB/O + AD/N' },
    { column: 'AG', formula: '=AA3 + AC3/O3 + AE3/N3', description: 'AA + AC/O + AE/N' },
    { column: 'AH', formula: '=X3 - AF3 - AG3', description: 'X - AF - AG' },
    { column: 'AI', formula: '=AF3 * U3', description: 'AF × U' },
    { column: 'AJ', formula: '=AG3 * U3', description: 'AG × U' },
    { column: 'AK', formula: '=AL3 - AJ3 - AI3', description: 'AL - AJ - AI' },
    { column: 'AM', formula: '=AH3 / 0.85', description: 'AH ÷ 0.85' },
    { column: 'AP', formula: '=AH3 - AM3*AN3*0.01 - AM3*AO3*0.01', description: 'AH - AM×AN×0.01 - AM×AO×0.01' },
    { column: 'AT', formula: '=X3 - AP3', description: 'X - AP' },
  ],
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
  if ('field' in rule && rule.field) return `필드: ${rule.field}`
  if ('field_digits' in rule && rule.field_digits) return `필드(숫자만): ${rule.field_digits}`
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
