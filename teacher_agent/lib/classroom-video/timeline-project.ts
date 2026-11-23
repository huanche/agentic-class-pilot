'use client';

import { measureSlideElementGeometry, slideToPng } from '@openmaic/renderer/snapshot';
import type { Slide } from '@openmaic/dsl';
import { compileVideoTimeline, emitHyperframes } from '@/lib/video-export';
import { packageVideoZip } from '@/lib/video-export-app/package-zip';
import type { ClassroomVideoPlan } from './types';
import { TIMELINE_VIDEO_RENDERER, usesTimelineVideo } from './renderer';

export interface TimelineProjectResult {
  projectBase64: string;
  duration: number;
  speech: { actionId: string; offset: number; duration: number }[];
}

/** Compile one immutable AI-trial scene with the same compiler/emitter as OpenMAIC export. */
export async function buildTimelineProject(
  plan: ClassroomVideoPlan,
  sceneId: string,
  durations: Record<string, number>,
  audioBase64: Record<string, string>,
): Promise<TimelineProjectResult> {
  if (plan.renderer !== TIMELINE_VIDEO_RENDERER || !usesTimelineVideo(plan.stage))
    throw new Error('此课件未启用测试版动画时间轴转换');
  const scene = plan.scenes.find((item) => item.id === sceneId);
  if (!scene || scene.type !== 'slide' || scene.content.type !== 'slide')
    throw new Error('找不到要转换的幻灯片');
  const clip = plan.clips.find((item) => item.sceneId === sceneId);
  if (!clip) throw new Error('视频快照缺少页面计划');
  const actions = scene.actions ?? [];
  for (const action of actions) {
    if (!['speech', 'spotlight', 'laser', 'reveal'].includes(action.type))
      throw new Error(`动画时间轴测试暂不支持此动作：${action.type}`);
    if (action.type === 'reveal' && action.pptxStep) throw new Error('原稿动画须使用高保真转换');
    if (
      action.type === 'speech' &&
      (!(durations[action.id] > 0) || !audioBase64[action.id] || !clip.audio[action.id])
    )
      throw new Error(`缺少有效配音：${action.id}`);
  }
  await document.fonts.ready;
  const canvas = scene.content.canvas;
  const geometry = await measureSlideElementGeometry(
    canvas,
    canvas.elements.map((el) => el.id),
  );
  const ir = compileVideoTimeline(
    { stage: plan.stage, scenes: [scene] },
    {
      timing: {
        audioDurationMs: (action) => durations[action.id] * 1000,
        videoDurationMs: () => null,
      },
      assets: {
        audio: (action) => ({
          id: action.id,
          format: clip.audio[action.id].file.split('.').pop(),
          present: true,
        }),
        media: () => null,
      },
      geometry: { contentGeometry: (id) => geometry.get(id) ?? null },
    },
  );
  const errors = ir.diagnostics.filter((d) => d.severity !== 'info');
  if (errors.length)
    throw new Error(`动画时间轴检查未通过：${errors.map((d) => d.message).join('；')}`);
  const blobs = new Map<string, Blob>();
  const reveals = actions.filter((action) => action.type === 'reveal');
  const hidden = new Set(reveals.map((action) => action.elementId));
  const snapshot = async (slide: Slide, transparent = false) => {
    const output = await slideToPng(slide, {
      width: 1280,
      pixelRatio: 1,
      format: 'blob',
      backgroundColor: transparent ? 'transparent' : '#fff',
    });
    return output instanceof Blob ? output : (await fetch(output)).blob();
  };
  for (const asset of ir.assets.entries.filter((item) => item.present && !item.dedupOf)) {
    if (asset.kind === 'frame') {
      blobs.set(
        asset.path,
        await snapshot({ ...canvas, elements: canvas.elements.filter((el) => !hidden.has(el.id)) }),
      );
    } else if (asset.kind === 'audio') {
      const binary = atob(audioBase64[asset.assetId]);
      blobs.set(asset.path, new Blob([Uint8Array.from(binary, (ch) => ch.charCodeAt(0))]));
    } else throw new Error(`动画素材尚未支持：${asset.kind}`);
  }
  const layers: Array<
    NonNullable<NonNullable<Parameters<typeof emitHyperframes>[1]>['revealLayers']>[number]
  > = [];
  for (const [index, action] of reveals.entries()) {
    const element = canvas.elements.find((el) => el.id === action.elementId);
    const marker = ir.scenes[0].markers.find((item) => item.actionId === action.id);
    if (!element || !marker) throw new Error('显示动作未匹配到画面元素或时间轴');
    const assetPath = `reveals/layer-${index}.png`;
    blobs.set(
      assetPath,
      await snapshot(
        {
          ...canvas,
          elements: [element],
          background: { type: 'solid', color: 'rgba(0,0,0,0)' },
        },
        true,
      ),
    );
    layers.push({
      sceneId,
      assetPath,
      startMs: marker.startMs,
      durationMs: marker.durationMs,
      effect: action.effect ?? 'fade-up',
      originX: geometry.get(element.id)?.centerX,
      originY: geometry.get(element.id)?.centerY,
    });
  }
  const project = emitHyperframes(ir, {
    width: 1280,
    height: 720,
    locale: 'zh-CN',
    revealLayers: layers,
  });
  const zip = await packageVideoZip(project, blobs);
  const bytes = new Uint8Array(await zip.arrayBuffer());
  let encoded = '';
  for (let offset = 0; offset < bytes.length; offset += 0x8000)
    encoded += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  return {
    projectBase64: btoa(encoded),
    duration: ir.totalDurationMs / 1000,
    speech: ir.scenes[0].narration.map((item) => ({
      actionId: item.actionId!,
      offset: item.startMs / 1000,
      duration: item.durationMs / 1000,
    })),
  };
}
