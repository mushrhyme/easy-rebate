/**
 * 양식지 타입(form_type) 목록 훅 - DB에서 동적 조회
 */
import { useQuery } from '@tanstack/react-query'
import { formTypesApi } from '@/api/client'

export type FormTypeOption = { value: string; label: string }

export function useFormTypes() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['form-types'],
    queryFn: () => formTypesApi.getList(),
  })
  const options: FormTypeOption[] = data?.form_types ?? []
  const formTypeLabel = (code: string | null): string => {
    if (!code) return '—'
    return options.find((o) => o.value === code)?.label ?? `型${code}`
  }
  return { options, formTypeLabel, isLoading, isError }
}
