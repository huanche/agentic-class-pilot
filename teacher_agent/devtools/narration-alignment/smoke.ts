/** Isolated live-model/TTS smoke test. Writes only synthetic samples to FOCUS_SMOKE_OUTPUT. */
import fs from 'node:fs/promises';
import path from 'node:path';
import { resolveModel } from '@/lib/server/resolve-model';
import { callLLM } from '@/lib/ai/llm';
import {
  generateAlignedSceneActions,
  FOCUS_REVIEW_SYSTEM,
} from '@/lib/server/aligned-scene-actions';
import { inspectSpeechFocus, parseFocusReview } from '@/lib/generation/speech-focus-contract';
import { withNarrationDuration } from '@/lib/generation/course-duration';
import {
  getServerTTSProviders,
  resolveTTSApiKey,
  resolveTTSBaseUrl,
} from '@/lib/server/provider-config';
import { generateTTS } from '@/lib/audio/tts-providers';
import { DEFAULT_TTS_MODELS, DEFAULT_TTS_VOICES, TTS_PROVIDERS } from '@/lib/audio/constants';
import { measureAudioDuration } from '@/lib/audio/audio-duration';
import type { PPTElement, Action } from '@openmaic/dsl';
import type { TTSProviderId } from '@/lib/audio/types';
import { buildPrompt } from '@openmaic/generation';

// Same header finalization as the production classroom TTS writer.
function finalizeWav(audio: Buffer): Buffer {
  if (
    audio.length < 44 ||
    audio.toString('ascii', 0, 4) !== 'RIFF' ||
    audio.toString('ascii', 8, 12) !== 'WAVE'
  )
    return audio;
  let offset = 12;
  while (offset + 8 <= audio.length) {
    const size = audio.readUInt32LE(offset + 4);
    if (audio.toString('ascii', offset, offset + 4) === 'data') {
      const fixed = Buffer.from(audio);
      fixed.writeUInt32LE(fixed.length - 8, 4);
      fixed.writeUInt32LE(fixed.length - offset - 8, offset + 4);
      return fixed;
    }
    const next = offset + 8 + size + (size % 2);
    if (next <= offset || next > audio.length) break;
    offset = next;
  }
  return audio;
}

const output = process.env.FOCUS_SMOKE_OUTPUT;
if (!output) throw new Error('Set FOCUS_SMOKE_OUTPUT to a fresh test output directory');
const safeError = console.error.bind(console);
console.error = () => safeError('[smoke] Upstream operation failed; provider payload omitted.');
process.on('uncaughtException', (error) => {
  safeError(
    JSON.stringify({
      check: 'failed',
      name: error.name,
      status: (error as Error & { statusCode?: number }).statusCode,
      reason: error.message.startsWith('Live reviewer incorrectly approved')
        ? error.message
        : 'Live generation or TTS test did not complete',
    }),
  );
  process.exit(1);
});
setTimeout(() => {
  safeError('Smoke test deadline exceeded');
  process.exit(124);
}, 540_000).unref();
await fs.mkdir(path.join(output, 'audio'), { recursive: true });
if (process.env.FOCUS_SMOKE_CHECK_ONLY === '1') {
  const prompt = buildPrompt('slide-actions', {
    title: 'Smoke',
    elements: 'text',
    description: '',
    keyPoints: '',
  });
  if (!prompt?.system.includes('Slide Action Generator'))
    throw new Error('Packaged slide prompts unavailable');
  console.log('Smoke bundle imports and embedded prompts verified; no model calls made.');
  process.exit(0);
}
const resolved = await resolveModel({ stage: 'scene-actions' });
const calls: Array<{ kind: string; milliseconds: number }> = [];
const aiCall = async (system: string, user: string) => {
  const start = Date.now();
  const response = await callLLM(
    {
      model: resolved.model,
      system,
      prompt: user,
      maxOutputTokens: 8192,
      maxRetries: 0,
      abortSignal: AbortSignal.timeout(90_000),
    },
    'scene-actions',
    undefined,
    resolved.thinkingConfig,
  );
  calls.push({
    kind: system.includes('[FOCUS_SPEECH_REVIEW]') ? 'review' : 'generate',
    milliseconds: Date.now() - start,
  });
  return response.text;
};
const prefix = `sample_${Date.now()}`;
const text = (id: string, content: string, top: number): PPTElement => ({
  id: `${prefix}_${id}`,
  type: 'text',
  content,
  left: 60,
  top,
  width: 880,
  height: 100,
  rotate: 0,
  defaultFontName: 'Microsoft YaHei',
  defaultColor: '#193455',
});
const errors = [
  text(
    'literal',
    '<p>SyntaxError：unterminated string literal</p><p>引号没有闭合，字符串没有结束</p>',
    130,
  ),
  text(
    'name',
    '<p>NameError：name is not defined</p><p>名称没有定义；字符串忘记加引号会被当成变量名</p>',
    260,
  ),
];
const bad: Action[] = [
  { id: 'bad-focus', type: 'spotlight', elementId: errors[1].id },
  {
    id: 'bad-speech',
    type: 'speech',
    text: 'unterminated string literal，字面意思就是没结束的字符串。第二个，NameError，名称错误。',
  },
];
const negativeInspection = inspectSpeechFocus(bad, errors);
const negativeIssues = parseFocusReview(
  await aiCall(
    FOCUS_REVIEW_SYSTEM,
    JSON.stringify({ elements: errors, segments: negativeInspection.segments }),
  ),
  negativeInspection.segments,
);
if (!negativeIssues.length)
  throw new Error('Live reviewer incorrectly approved the known cross-topic mismatch');
console.log(JSON.stringify({ check: 'known-mismatch-rejected', passed: true }));

const cases = [
  {
    title: 'Python：区分语法错误与名称错误',
    instruction:
      '分别讲清楚两种报错的原因。字符串没有结束时指向语法错误区域；名称未定义时指向名称错误区域。每个知识点一个聚焦单元。',
    elements: errors,
  },
  {
    title: '比较编辑器',
    instruction:
      '比较 IDLE 和 VS Code 的配置与适用阶段，讲比较内容时指向比较表。最后再给出工具建议，不能在比较表时高亮建议框。',
    elements: [
      {
        id: `${prefix}_table`,
        type: 'table',
        left: 60,
        top: 150,
        width: 880,
        height: 180,
        rotate: 0,
        colWidths: [0.25, 0.45, 0.3],
        cellMinHeight: 40,
        data: [
          [{ text: '工具' }, { text: '特点' }, { text: '适合阶段' }],
          [{ text: 'IDLE' }, { text: '随 Python 自带，零配置' }, { text: '第一周入门' }],
          [{ text: 'VS Code' }, { text: '插件丰富，需要安装 Python 扩展' }, { text: '主流推荐' }],
        ].map((row, i) =>
          row.map((cell, j) => ({ ...cell, id: `cell_${i}_${j}`, colspan: 1, rowspan: 1 })),
        ),
      } as unknown as PPTElement,
      text('advice', '建议：先跑通流程，不折腾工具；练习文件统一放进课程文件夹。', 380),
    ],
  },
  {
    title: '赋值后的类型转换',
    instruction:
      '先解释 int i = 2.56 转换后的值，再解释连续赋值 a = b = c = 5。最后 reveal 并解释结论。两个例子不能跨目标混在同一个 speech 中。',
    elements: [
      text('cast', 'int i = 2.56; 转换后的 i 为 2', 130),
      text('chain', 'a = b = c = 5; 从右向左，三者均为 5', 260),
      text('conclusion', '结论：赋值先计算右侧，再转换为左侧变量的类型。', 390),
    ],
  },
];
const ttsId = Object.entries(getServerTTSProviders()).find(
  ([id, config]) => id !== 'browser-native-tts' && !config.disabled,
)?.[0] as TTSProviderId | undefined;
if (process.env.FOCUS_SMOKE_TTS === '1' && !ttsId)
  throw new Error('No managed TTS provider available');
const scenes = [];
let audioNumber = 0;
for (const [index, item] of cases.entries()) {
  const elements = [text(`title_${index}`, item.title, 25), ...item.elements];
  const outline = withNarrationDuration({
    id: `outline_${index}`,
    type: 'slide',
    title: item.title,
    description: item.instruction,
    keyPoints: [],
    order: index + 1,
    durationBudget: { targetSeconds: 30 },
  });
  const actions = await generateAlignedSceneActions(outline, { elements }, aiCall, {
    languageDirective: '使用简体中文讲解，保留代码和报错名称。',
  });
  const speeches = actions.filter((action) => action.type === 'speech');
  if (speeches.length > 12 || speeches.reduce((sum, action) => sum + action.text.length, 0) > 1200)
    throw new Error('Unexpectedly large smoke narration; refusing unbounded TTS calls');
  let seconds = 0;
  if (process.env.FOCUS_SMOKE_TTS === '1' && ttsId) {
    for (const speech of speeches) {
      const result = await generateTTS(
        {
          providerId: ttsId,
          apiKey: resolveTTSApiKey(ttsId),
          baseUrl:
            resolveTTSBaseUrl(ttsId) ||
            TTS_PROVIDERS[ttsId as keyof typeof TTS_PROVIDERS]?.defaultBaseUrl,
          modelId: DEFAULT_TTS_MODELS[ttsId as keyof typeof DEFAULT_TTS_MODELS],
          voice: DEFAULT_TTS_VOICES[ttsId as keyof typeof DEFAULT_TTS_VOICES],
        },
        speech.text,
      );
      const bytes = result.format === 'wav' ? finalizeWav(Buffer.from(result.audio)) : result.audio;
      const filename = `audio-${++audioNumber}.${result.format}`;
      await fs.writeFile(path.join(output, 'audio', filename), bytes);
      Object.assign(speech, { audioRef: `audio/${filename}` });
      seconds += measureAudioDuration(bytes, result.format) ?? 0;
    }
  }
  scenes.push({
    id: `scene_${index}`,
    stageId: 'focus-smoke',
    order: index + 1,
    type: 'slide',
    title: item.title,
    actions,
    content: {
      type: 'slide',
      canvas: {
        id: `canvas_${index}`,
        viewportSize: 1000,
        viewportRatio: 0.5625,
        background: { type: 'solid', color: '#ffffff' },
        elements,
      },
    },
  });
  await fs.writeFile(
    path.join(output, 'samples.json'),
    JSON.stringify({ scenes, calls, model: resolved.modelString, negativeIssues }, null, 2),
  );
  console.log(
    JSON.stringify({
      check: 'generated-page',
      page: index + 1,
      approved: true,
      speechSegments: speeches.length,
      seconds: Number(seconds.toFixed(2)),
    }),
  );
}
console.log(
  JSON.stringify({
    check: 'complete',
    pages: scenes.length,
    audioClips: audioNumber,
    modelCalls: calls.length,
  }),
);
process.exit(0);
