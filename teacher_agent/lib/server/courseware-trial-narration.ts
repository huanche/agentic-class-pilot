import { nanoid } from 'nanoid';
import { trialSpeechAudio } from '@/lib/generation/courseware-trial';
import type { Action } from '@/lib/types/action';
import type { Scene } from '@/lib/types/stage';
import {
  ClassroomSnapshotConflictError,
  persistClassroom,
  readClassroom,
  type PersistedClassroomData,
} from './classroom-storage';
import {
  finalizeClassroomTtsAudio,
  generateTTSForClassroom,
  removeClassroomTtsAudio,
} from './classroom-media-generation';
import { createOpenmaicCoursewareSteps } from './openmaic-courseware-steps';
import type { PlatformUserModelConfig } from './platform-user-model-config';

interface TrialNarrationRequest {
  sceneId?: string;
  revision?: number;
  regenerate?: boolean;
  segments?: Record<string, string>;
}

export async function reviseTrialNarration(
  classroomId: string,
  request: TrialNarrationRequest,
  baseUrl: string,
  teacherId: string,
  config: PlatformUserModelConfig | null | undefined,
  signal: AbortSignal,
) {
  const classroom = await readClassroom(classroomId);
  const trial = classroom?.stage.coursewareTrial;
  const plan = classroom?.stage.generationPlan;
  const scene = classroom?.scenes.find((item) => item.id === request.sceneId);
  const outline = plan?.outlines.find((item) => item.id === scene?.outlineId);
  if (
    !classroom ||
    !trial ||
    !plan?.complete ||
    !outline ||
    !scene ||
    scene.content.type !== 'slide'
  )
    throw new Error('此页试用讲稿不可修改');
  const revision = trial.revision ?? 0;
  if (revision !== request.revision) throw new ClassroomSnapshotConflictError();
  const existing = scene.actions ?? [];
  let proposed: Action[];
  if (request.regenerate) {
    const previous = classroom.scenes
      .filter((page) => page.order < scene.order && page.type !== 'quiz')
      .at(-1);
    const generate = createOpenmaicCoursewareSteps(
      {
        stage: classroom.stage,
        outlines: plan.outlines,
        sessionId: classroomId,
        agents: [],
        requirements: { requirement: trial.overview, webSearch: false },
        enableTTS: true,
        enableMedia: false,
      },
      config,
      {},
    );
    proposed = (await generate.actions(outline, scene.content, previous, signal)).actions ?? [];
  } else {
    const edits = request.segments;
    if (!edits || typeof edits !== 'object' || Array.isArray(edits))
      throw new Error('请填写本页讲稿');
    const speechIds = new Set(
      existing.filter((action) => action.type === 'speech').map((action) => action.id),
    );
    for (const [id, text] of Object.entries(edits)) {
      if (!speechIds.has(id) || typeof text !== 'string' || !text.trim() || text.length > 2000)
        throw new Error('每段讲稿须填写 1 至 2000 字');
    }
    proposed = existing.map((action) =>
      action.type === 'speech' && Object.hasOwn(edits, action.id)
        ? { ...action, text: edits[action.id].trim() }
        : action,
    );
  }

  const original = new Map(existing.map((action) => [action.id, action]));
  const pending = new Map<string, Scene>();
  const unusedAudio = existing.filter((action) => action.type === 'speech');
  proposed = proposed.map((action) => {
    if (action.type !== 'speech') return action;
    const old = original.get(action.id);
    const reuse = request.regenerate
      ? unusedAudio.find(
          (prior) =>
            prior.text === action.text && prior.speed === action.speed && trialSpeechAudio(prior),
        )
      : old;
    if (reuse?.type === 'speech' && reuse.text === action.text && trialSpeechAudio(reuse)) {
      const index = unusedAudio.indexOf(reuse);
      if (index >= 0) unusedAudio.splice(index, 1);
      return reuse;
    }
    const speech = { ...action, id: nanoid(), audioUrl: undefined, audioId: undefined };
    pending.set(speech.id, { ...scene, actions: [speech] });
    return speech;
  });
  if (!proposed.some((action) => action.type === 'speech')) throw new Error('本页没有可配音讲稿');
  if (!request.regenerate && pending.size === 0) return { revision };
  try {
    for (const fragment of pending.values()) {
      const result = await generateTTSForClassroom([fragment], classroomId, baseUrl, config?.tts, {
        signal,
        isolateAudio: true,
        failFast: true,
        voiceSelection: trial.voice,
        cacheScope: teacherId,
        languageDirective: classroom.stage.languageDirective,
      });
      if (!result.generated || result.failed) throw new Error('配音未完成，请检查语音服务后重试');
    }
    for (const fragment of pending.values())
      await finalizeClassroomTtsAudio(fragment, classroomId, baseUrl);
    const updated: Scene = {
      ...scene,
      actions: proposed.flatMap((action) => pending.get(action.id)?.actions ?? [action]),
      timing: scene.timing && {
        ...scene.timing,
        measuredDurationSec: undefined,
        measurementKey: undefined,
        durationStatus: 'unmeasured',
      },
    };
    const next: PersistedClassroomData = {
      ...classroom,
      stage: {
        ...classroom.stage,
        updatedAt: Date.now(),
        coursewareTrial: { ...trial, revision: revision + 1 },
      },
      scenes: classroom.scenes.map((page) => (page.id === scene.id ? updated : page)),
    };
    await persistClassroom(next, baseUrl, {
      expectedTrial: { revision, updatedAt: classroom.stage.updatedAt },
    });
    return { revision: revision + 1 };
  } catch (error) {
    await Promise.allSettled(
      [...pending.values()].map((fragment) => removeClassroomTtsAudio(fragment, classroomId)),
    );
    throw error;
  }
}
