/**
 * 양식지별 설정
 */
import type { FormConfig, FormType } from '@/types'

export const FORM_TYPES: FormType[] = ['01', '02', '03', '04', '05']

export const FORM_CONFIGS: Record<FormType, FormConfig> = {
  '01': {
    name: '01 FINET',
    color: '#667eea',
    imagePath: '/images/form_01.png', // 프로젝트 루트의 form_01.png 파일 경로
  },
  '02': {
    name: '02 ヤマエ',
    color: '#4ECDC4',
    imagePath: '/images/form_02.png', // 프로젝트 루트의 form_02.png 파일 경로
  },
  '03': {
    name: '03 旭食品/ヤマキ',
    color: '#45B7D1',
    imagePath: '/images/form_03.png', // 프로젝트 루트의 form_03.png 파일 경로
  },
  '04': {
    name: '04 ACCESS',
    color: '#a78bfa',
    imagePath: '/images/form_04.png', // 프로젝트 루트의 form_04.png 파일 경로
  },
  '05': {
    name: '05 湧川',
    color: '#98D8C8',
    imagePath: '/images/form_05.png', // 프로젝트 루트의 form_05.png 파일 경로
  },
}
