import { describe, expect, it } from 'vitest';
import { normalizeQwenWav } from '@/lib/audio/tts-providers';

describe('normalizeQwenWav', () => {
  it('repairs streaming placeholder lengths without changing PCM bytes', () => {
    const wav = new Uint8Array(48);
    wav.set(Buffer.from('RIFF'), 0);
    wav.set(Buffer.from('WAVEfmt '), 8);
    wav.set(Buffer.from('data'), 36);
    const view = new DataView(wav.buffer);
    view.setUint32(4, 0x7fffffff, true);
    view.setUint32(16, 16, true);
    view.setUint32(40, 0x7fffffff, true);
    wav.set([1, 2, 3, 4], 44);

    const fixed = normalizeQwenWav(wav);
    const header = new DataView(fixed.buffer);
    expect(header.getUint32(4, true)).toBe(40);
    expect(header.getUint32(40, true)).toBe(4);
    expect([...fixed.slice(44)]).toEqual([1, 2, 3, 4]);
    expect(view.getUint32(4, true)).toBe(0x7fffffff);
  });

  it('leaves non-WAV audio unchanged', () => {
    const bytes = new Uint8Array([1, 2, 3, 4]);
    expect(normalizeQwenWav(bytes)).toBe(bytes);
  });
});
