import type { TTSVoiceInfo } from './types';

export const HOJO_40M_MODEL = 'hojo-tts-light-40m';
export const HOJO_80M_MODEL = 'hojo-tts-light-80m';
export const HOJO_DEFAULT_VOICE = 'hojo_zh_f_01';
export const HOJO_REFERENCE_VOICE = 'hojo_80m_zh1';
export const HOJO_CLONE_PREFIX = 'hojo_clone_';
export const HOJO_VOICES: TTSVoiceInfo[] = [
  ...['hojo_zh_f_01', 'hojo_zh_f_02'].map((id, index) => ({
    id,
    name: `中文女声 ${index + 1}`,
    language: 'zh-CN',
    gender: 'female' as const,
    compatibleModels: [HOJO_40M_MODEL],
  })),
  ...['female', 'male'].flatMap((gender) =>
    Array.from({ length: gender === 'female' ? 8 : 5 }, (_, index) => ({
      id: `hojo_en_${gender === 'female' ? 'f' : 'm'}_${String(index + 1).padStart(2, '0')}`,
      name: `English ${gender} ${index + 1}`,
      language: 'en-US',
      gender: gender as 'female' | 'male',
      compatibleModels: [HOJO_40M_MODEL],
    })),
  ),
  {
    id: HOJO_REFERENCE_VOICE,
    name: '官方中文示例音色',
    language: 'zh-CN',
    gender: 'female',
    compatibleModels: [HOJO_80M_MODEL],
  },
];
