/**
 * 양식별 설정(config/form_types.json) 훅 - 필드명, NET 계산, SAP 매핑 등
 */
import { useQuery } from '@tanstack/react-query'
import { formTypesApi, type FormTypesConfig, type FormTypeConfig } from '@/api/client'

export function useFormTypesConfig() {
  const { data, isLoading } = useQuery<FormTypesConfig>({
    queryKey: ['form-types-config'],
    queryFn: () => formTypesApi.getConfig(),
    staleTime: 5 * 60 * 1000, // 5분 캐싱
  })
  return { config: data ?? null, isLoading }
}

/**
 * formType(01~05)에 대응하는 config를 조회. 0-padding 유무 모두 지원.
 */
export function getFormConfig(
  config: FormTypesConfig | null,
  formType: string | null,
): FormTypeConfig | null {
  if (!config || !formType) return null
  const norm = formType.trim()
  // "01" 형태로 먼저 시도, 없으면 "1" 형태로
  return config[norm] ?? config[norm.replace(/^0+/, '')] ?? config[norm.padStart(2, '0')] ?? null
}

/**
 * FORM_AMOUNT_LAYOUT 대체: config에서 금액 필드명 추출
 */
export function getAmountLayout(
  config: FormTypesConfig | null,
  formType: string | null,
): { a1: string; a2: string; final: string } | null {
  const fc = getFormConfig(config, formType)
  if (!fc) return null
  return {
    a1: fc.fields.amount1,
    a2: fc.fields.amount2,
    final: fc.fields.final_amount,
  }
}

/**
 * NET 계산: config의 net_calculation.type 기반으로 조건 필드명 반환
 */
export function getNetConditionFields(
  config: FormTypesConfig | null,
  formType: string | null,
): { type: string; cond1: string; cond2: string; csDivideByIrisu: boolean; fallbackField: string | null } | null {
  const fc = getFormConfig(config, formType)
  if (!fc) return null
  const netCalc = fc.net_calculation as unknown as Record<string, unknown>
  return {
    type: fc.net_calculation.type,
    cond1: fc.fields.condition1,
    cond2: fc.fields.condition2,
    csDivideByIrisu: !!(netCalc?.cs_divide_by_irisu),
    fallbackField: (netCalc?.fallback_field as string) ?? null,
  }
}
