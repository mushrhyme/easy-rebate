/**
 * 업로드 채널 설정: FINET(엑셀) / 우편물(Upstage OCR)
 * 양식지 타입(form_type)은 API /api/form-types 에서 동적 조회
 */
import type { UploadChannelConfig, UploadChannel } from '@/types'

export const UPLOAD_CHANNELS: UploadChannel[] = ['finet', 'mail']

export const UPLOAD_CHANNEL_CONFIGS: Record<UploadChannel, UploadChannelConfig> = {
  finet: {
    name: 'FINET',
    label: 'Excel変換',
    color: '#667eea',
    imagePath: '/images/form_01.png',
  },
  mail: {
    name: '郵便物',
    label: 'OCR',
    color: '#a78bfa',
    imagePath: '/images/form_04.png',
  },
}
