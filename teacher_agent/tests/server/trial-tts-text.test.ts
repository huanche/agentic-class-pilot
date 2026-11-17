import { afterEach, expect, test, vi } from 'vitest';
import { prepareTrialNarration, verbalizeTrialSpeech } from '@/lib/server/trial-tts-text';

afterEach(() => vi.unstubAllEnvs());

test('reads ambiguous C symbols only in their stated context', () => {
  const text =
    '先看 int a[20]。如果 sizeof(short) 等于 2 B，数组占 40 B。' +
    '执行 return a[i]，就返回 a[i]。x * y 是乘法，*p 是取指针 p 指向的值。';
  const spoken = verbalizeTrialSpeech(text);
  expect(spoken).toContain('包含20个整型元素的数组 A');
  expect(spoken).toContain('占2个字节');
  expect(spoken).toContain('占 40个字节');
  expect(spoken).toContain('执行这条 return 语句，就返回数组 a 中下标为 i 的元素');
  expect(spoken).toContain('x 和 y 之间的星号表示相乘');
  expect(spoken).toContain('写在指针 p 前面的星号');
  expect(verbalizeTrialSpeech('比较 int a[3][4]、*p、x * y 和型号 ABC-1234。')).toBe(
    '比较 int a[3][4]、*p、x * y 和型号 ABC-1234。',
  );
});

test('keeps code rewrites usable when the local normalizer is unavailable', async () => {
  vi.stubEnv('COURSEWARE_TRIAL_TN_PYTHON', 'missing-trial-normalizer');
  await expect(prepareTrialNarration(['数组占 2 B。', 'Use 2 bytes.'])).resolves.toEqual([
    '数组占 2个字节。',
    'Use 2 bytes.',
  ]);
});

test('respects cancellation before starting preparation', async () => {
  await expect(prepareTrialNarration(['数组按行存放'], AbortSignal.abort())).rejects.toThrow();
});
