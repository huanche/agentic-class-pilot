import { mkdtempSync, mkdirSync, writeFileSync } from 'fs';
import os from 'os';
import path from 'path';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Scene } from '@/lib/types/stage';

/**
 * attachNarrationServingUrls re-derives serving URLs from on-disk narration
 * files so a classroom saved from a converted browser document (pool-local
 * ast_* ids, URLs dropped) stays playable on every other browser.
 */
describe('attachNarrationServingUrls', () => {
  let classroomsDir: string;

  beforeEach(() => {
    vi.resetModules();
    classroomsDir = mkdtempSync(path.join(os.tmpdir(), 'classrooms-attach-'));
  });

  async function loadModule() {
    return import('@/lib/server/classroom-storage');
  }

  function speechScene(order: number, actions: Array<Record<string, unknown>>): Scene {
    return {
      id: `scene_${order}`,
      stageId: 'stage_1',
      type: 'slide',
      title: 'Scene',
      order,
      content: { type: 'slide', canvas: { id: 'canvas', elements: [] } },
      actions: actions.map((a, i) => ({ type: 'speech', id: `action_${i}`, ...a })),
    } as unknown as Scene;
  }

  it('stamps the serving URL when the narration file exists on disk', async () => {
    process.env.CLASSROOMS_DATA_DIR = classroomsDir;
    const { attachNarrationServingUrls } = await loadModule();
    const file = path.join(classroomsDir, 'cls_1', 'audio', 'tts_s1_action_0.wav');
    mkdirSync(path.dirname(file), { recursive: true });
    writeFileSync(file, Buffer.from('RIFF'));

    const scene = speechScene(1, [{ audioId: 'ast_local_pool_id', text: '你好' }]);
    const [next] = await attachNarrationServingUrls([scene], 'cls_1', 'https://teacher.example');

    expect(next).not.toBe(scene);
    const action = next.actions![0] as unknown as { audioUrl?: string };
    expect(action.audioUrl).toMatch(
      /^https:\/\/teacher\.example\/api\/classroom-media\/cls_1\/audio\/tts_s1_action_0\.wav\?v=\d+-\d+$/,
    );
  });

  it('keeps an action untouched when it already carries a URL', async () => {
    process.env.CLASSROOMS_DATA_DIR = classroomsDir;
    const { attachNarrationServingUrls } = await loadModule();
    const file = path.join(classroomsDir, 'cls_1', 'audio', 'tts_s1_action_0.wav');
    mkdirSync(path.dirname(file), { recursive: true });
    writeFileSync(file, Buffer.from('RIFF'));

    const existing = 'https://teacher.example/api/classroom-media/cls_1/audio/keep-me.wav';
    const scene = speechScene(1, [{ audioId: 'ast_1', audioUrl: existing, text: '你好' }]);
    const [next] = await attachNarrationServingUrls([scene], 'cls_1', 'https://teacher.example');

    expect(next).toBe(scene);
    expect((next.actions![0] as unknown as { audioUrl: string }).audioUrl).toBe(existing);
  });

  it('skips actions without audio, invalidated actions, and missing files', async () => {
    process.env.CLASSROOMS_DATA_DIR = classroomsDir;
    const { attachNarrationServingUrls } = await loadModule();
    const scene = speechScene(1, [
      { text: '没有 audioId' },
      { audioId: 'ast_2', audioInvalidated: true, text: '已失效' },
      { audioId: 'ast_3', text: '磁盘上没有文件' },
      { audioId: 'ast_4', id: '../escape', text: '路径穿越' },
    ]);
    const result = await attachNarrationServingUrls([scene], 'cls_1', 'https://teacher.example');

    expect(result[0]).toBe(scene);
  });

  it('probes mp3 besides wav and returns the input by identity when nothing matches', async () => {
    process.env.CLASSROOMS_DATA_DIR = classroomsDir;
    const { attachNarrationServingUrls } = await loadModule();
    const file = path.join(classroomsDir, 'cls_2', 'audio', 'tts_s2_action_0.mp3');
    mkdirSync(path.dirname(file), { recursive: true });
    writeFileSync(file, Buffer.from('ID3'));

    const stamped = speechScene(2, [{ audioId: 'ast_mp3', text: 'hi' }]);
    const [withMp3] = await attachNarrationServingUrls([stamped], 'cls_2', 'https://t.example');
    expect((withMp3.actions![0] as unknown as { audioUrl: string }).audioUrl).toContain(
      'tts_s2_action_0.mp3',
    );

    const empty = speechScene(3, [{ audioId: 'ast_none', text: 'hi' }]);
    const result = await attachNarrationServingUrls([empty], 'cls_2', 'https://t.example');
    expect(result[0]).toBe(empty);
  });
});
