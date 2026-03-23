/**
 * 복잡한 구조 필드 상세 (배지 클릭 시)
 * - JSON 문자열(이중 직렬화 등)은 파싱 후 표시
 * - 객체 배열은 데이터프레임 형태(열=키, 행=레코드)
 * - 그 외는 키/값 플랫 테이블
 */
import type { ReactNode } from 'react'

/** page_meta 등에서 오는 문자열이 JSON 객체/배열이면 파싱 시도 → { "a":1 } 형태 */
function tryParseJsonString(s: string): unknown | null {
  const t = s.trim()
  if (
    (t.startsWith('{') && t.endsWith('}')) ||
    (t.startsWith('[') && t.endsWith(']'))
  ) {
    try {
      return JSON.parse(t) as unknown
    } catch {
      return null
    }
  }
  return null
}

/** 문자열로 여러 번 직렬화된 값 언랩 (최대 depth) */
class StructuredValueParser {
  static unwrapJsonStrings(value: unknown, maxDepth = 4): unknown {
    let v = value
    let d = 0
    while (d < maxDepth && typeof v === 'string') {
      const parsed = tryParseJsonString(v)
      if (parsed === null) break
      v = parsed
      d++
    }
    return v
  }

  static isPlainObject(v: unknown): v is Record<string, unknown> {
    return v !== null && typeof v === 'object' && !Array.isArray(v)
  }

  /** 동질 객체 배열 → 데이터프레임 렌더링 대상 */
  static isArrayOfPlainObjects(v: unknown): v is Record<string, unknown>[] {
    return (
      Array.isArray(v) &&
      v.length > 0 &&
      v.every((x) => StructuredValueParser.isPlainObject(x))
    )
  }

  /** 행들에서 열 순서: 첫 행 키 우선, 이후 등장 키 순 */
  static collectColumnKeys(rows: Record<string, unknown>[]): string[] {
    const seen = new Set<string>()
    const ordered: string[] = []
    for (const row of rows) {
      for (const k of Object.keys(row)) {
        if (!seen.has(k)) {
          seen.add(k)
          ordered.push(k)
        }
      }
    }
    return ordered
  }
}

/** 셀에 넣을 스칼라/중첩 표시 (중첩은 JSON 블록) */
function formatCellDisplay(v: unknown): ReactNode {
  if (v === null || v === undefined) {
    return <span className="complex-field-cell-empty">—</span>
  }
  if (
    typeof v === 'string' ||
    typeof v === 'number' ||
    typeof v === 'boolean'
  ) {
    return String(v)
  }
  return (
    <pre className="complex-field-cell-json">
      {JSON.stringify(v, null, 2)}
    </pre>
  )
}

/** 중첩 객체를 flatten. 예: { a: { b: 1 } } → [{ key: 'a.b', value: '1' }] */
export function flattenObject(
  obj: unknown,
  prefix = ''
): Array<{ key: string; value: string }> {
  const result: Array<{ key: string; value: string }> = []
  if (obj === null || obj === undefined) {
    return [{ key: prefix || 'null', value: 'null' }]
  }
  if (Array.isArray(obj)) {
    obj.forEach((item, index) => {
      if (typeof item === 'object' && item !== null) {
        result.push(
          ...flattenObject(item, prefix ? `${prefix}[${index}]` : `[${index}]`)
        )
      } else {
        result.push({
          key: prefix ? `${prefix}[${index}]` : `[${index}]`,
          value: String(item),
        })
      }
    })
  } else if (typeof obj === 'object') {
    Object.keys(obj).forEach((key) => {
      const newKey = prefix ? `${prefix}.${key}` : key
      const value = (obj as Record<string, unknown>)[key]
      if (value === null || value === undefined) {
        result.push({ key: newKey, value: 'null' })
      } else if (typeof value === 'object' || Array.isArray(value)) {
        result.push(...flattenObject(value, newKey))
      } else {
        result.push({ key: newKey, value: String(value) })
      }
    })
  } else {
    result.push({ key: prefix || 'value', value: String(obj) })
  }
  return result
}

interface ComplexFieldDetailProps {
  keyName: string
  value: unknown
  onClose: () => void
}

/** 객체 배열 → 열 헤더 + 행 (데이터프레임) */
function DataframeView({
  rows,
}: {
  rows: Record<string, unknown>[]
}) {
  const columns = StructuredValueParser.collectColumnKeys(rows)
  return (
    <div className="complex-field-dataframe-wrap">
      <table className="complex-field-dataframe">
        <thead>
          <tr>
            <th className="complex-field-df-index">#</th>
            {columns.map((col) => (
              <th key={col} title={col}>
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri}>
              <td className="complex-field-df-index">{ri + 1}</td>
              {columns.map((col) => (
                <td key={col} className="complex-field-df-cell">
                  {formatCellDisplay(row[col])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function ComplexFieldDetail({
  keyName,
  value,
  onClose,
}: ComplexFieldDetailProps) {
  const normalized = StructuredValueParser.unwrapJsonStrings(value)

  const body = (() => {
    if (StructuredValueParser.isArrayOfPlainObjects(normalized)) {
      return <DataframeView rows={normalized} />
    }
    const items = flattenObject(normalized)
    if (items.length === 0) {
      return (
        <p className="complex-field-empty-msg">（データがありません）</p>
      )
    }
    return (
      <table className="complex-field-table">
        <thead>
          <tr>
            <th>キー</th>
            <th>値</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, index) => (
            <tr key={index}>
              <td className="complex-field-key">{item.key}</td>
              <td className="complex-field-value">{item.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    )
  })()

  return (
    <div className="complex-field-detail">
      <div className="complex-field-detail-header">
        <h3>{keyName}</h3>
        <button
          className="complex-field-detail-close"
          onClick={onClose}
          type="button"
        >
          ×
        </button>
      </div>
      <div className="complex-field-detail-content">{body}</div>
    </div>
  )
}
