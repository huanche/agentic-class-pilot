import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import type { Scene, Stage } from '@/lib/types/stage';

vi.mock('@/lib/server/course-space-database', () => ({
  isCourseDatabaseConfigured: () => false,
  readClassroomFromDatabase: async () => undefined,
  upsertClassroomDatabaseRecord: async () => undefined,
}));
const directory = path.join(process.cwd(), '.runtime', 'snapshot-ownership-tests');
let storage: typeof import('@/lib/server/classroom-storage');
const stage = (id: string, complete: boolean): Stage => ({
  id,
  name: 'Signal analysis',
  createdAt: 1,
  updatedAt: 2,
  generationPlan: { version: 1, outlines: [], complete, serverJobId: 'cw_signal' },
});
const scenes = [
  { id: 'first', order: 1 },
  { id: 'second', order: 2 },
] as Scene[];

beforeAll(async () => {
  vi.stubEnv('CLASSROOMS_DATA_DIR', directory);
  storage = await import('@/lib/server/classroom-storage');
});
afterAll(async () => {
  await fs.rm(directory, { recursive: true, force: true });
  vi.unstubAllEnvs();
});

describe('server generation snapshot ownership', () => {
  it('rejects an old browser document that dropped the job and would erase completed pages', async () => {
    const savedStage = stage('stale-browser', true);
    await storage.persistClassroom(
      { id: savedStage.id, stage: savedStage, scenes },
      'http://localhost',
    );
    const oldStage = {
      ...savedStage,
      generationPlan: { version: 1 as const, outlines: [], complete: false },
    };
    await expect(
      storage.persistClassroom(
        { id: savedStage.id, stage: oldStage, scenes: [scenes[1]] },
        'http://localhost',
        { source: 'browser' },
      ),
    ).rejects.toThrow('服务器课件已更新');
    expect((await storage.readClassroom(savedStage.id))?.scenes).toEqual(scenes);
    expect((await storage.readClassroom(savedStage.id))?.stage.generationPlan?.serverJobId).toBe(
      'cw_signal',
    );
  });

  it('rejects browser writes while the matching server job is still generating', async () => {
    const pending = stage('active-job', false);
    await storage.persistClassroom(
      { id: pending.id, stage: pending, scenes: [] },
      'http://localhost',
    );
    await expect(
      storage.persistClassroom(
        {
          id: pending.id,
          stage: { ...pending, generationPlan: { ...pending.generationPlan!, complete: true } },
          scenes,
        },
        'http://localhost',
        { source: 'browser' },
      ),
    ).rejects.toThrow('服务器课件已更新');
    expect((await storage.readClassroom(pending.id))?.scenes).toHaveLength(0);
  });

  it('allows teacher edits and intentional page deletion after loading the completed job', async () => {
    const complete = stage('teacher-edit', true);
    await storage.persistClassroom(
      { id: complete.id, stage: complete, scenes },
      'http://localhost',
    );
    await storage.persistClassroom(
      { id: complete.id, stage: complete, scenes: [scenes[1]] },
      'http://localhost',
      { source: 'browser' },
    );
    expect((await storage.readClassroom(complete.id))?.scenes).toEqual([scenes[1]]);
  });

  it('keeps standalone browser generation and server worker writes working', async () => {
    const standalone = { ...stage('standalone', false), generationPlan: undefined };
    await storage.persistClassroom(
      { id: standalone.id, stage: standalone, scenes },
      'http://localhost',
      { source: 'browser' },
    );
    expect((await storage.readClassroom(standalone.id))?.scenes).toHaveLength(2);
    const server = stage('worker', false);
    await storage.persistClassroom(
      { id: server.id, stage: server, scenes: [] },
      'http://localhost',
    );
    await storage.persistClassroom(
      {
        id: server.id,
        stage: { ...server, generationPlan: { ...server.generationPlan!, complete: true } },
        scenes,
      },
      'http://localhost',
    );
    expect((await storage.readClassroom(server.id))?.scenes).toHaveLength(2);
  });
});
