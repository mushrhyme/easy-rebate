/**
 * 복잡한 구조 필드 상세 테이블 (배지 클릭 시 키/값 표시)
 */

/** 중첩 객체를 flatten. 예: { a: { b: 1 } } → [{ key: 'a.b', value: '1' }] */
export function flattenObject(obj: unknown, prefix = ''): Array<{ key: string; value: string }> {
  const result: Array<{ key: string; value: string }> = []
  if (obj === null || obj === undefined) {
    return [{ key: prefix || 'null', value: 'null' }]
  }
  if (Array.isArray(obj)) {
    obj.forEach((item, index) => {
      if (typeof item === 'object' && item !== null) {
        result.push(...flattenObject(item, prefix ? `${prefix}[${index}]` : `[${index}]`))
      } else {
        result.push({ key: prefix ? `${prefix}[${index}]` : `[${index}]`, value: String(item) })
      }
    })
  } else if (typeof obj === 'object') {
    Object.keys(obj).forEach((key) => {
      const newKey = prefix ? `${prefix}.${key}` : key
      const value = obj[key as keyof typeof obj]
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
  /** 표시할 필드 키 */
  keyName: string
  /** 값 (객체/배열 등) */
  value: unknown
  onClose: () => void
}

export function ComplexFieldDetail({ keyName, value, onClose }: ComplexFieldDetailProps) {
  const items = flattenObject(value)
  return (
    <div className="complex-field-detail">
      <div className="complex-field-detail-header">
        <h3>{keyName}</h3>
        <button className="complex-field-detail-close" onClick={onClose} type="button">
          ×
        </button>
      </div>
      <div className="complex-field-detail-content">
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
      </div>
    </div>
  )
}
