import { spawn } from 'child_process';
import { promises as fs } from 'fs';
import path from 'path';
import { randomUUID } from 'crypto';
import { callLLM } from '@/lib/ai/llm';
import { resolveModel } from '@/lib/server/resolve-model';
import {
  COURSE_SPACES_DIR,
  listCourseArtifacts,
  listCourseJobs,
  readMaterialExtraction,
  readServerCourse,
} from '@/lib/server/course-space-storage';
import { loadTeacherWorkspaceSkills } from '@/lib/server/teacher-workspace-skills';
import type { CourseArtifactJob } from '@/lib/course-space/types';

export type TeacherAgentMode = 'deepseek-harness' | 'deepseek-compatible';

type ChatMessage = { role: 'user' | 'assistant'; content: string };

function safeSessionId(value: string) {
  return value.replace(/[^a-zA-Z0-9_-]/g, '-').slice(0, 80) || 'teacher-workspace';
}

async function writePlugin(dir: string, name: string, description: string, content: unknown) {
  const pluginDir = path.join(dir, 'plugins', name);
  await fs.mkdir(pluginDir, { recursive: true });
  await fs.writeFile(
    path.join(pluginDir, 'plugin.json'),
    JSON.stringify({ name, description, version: 1 }, null, 2),
  );
  await fs.writeFile(path.join(pluginDir, 'context.json'), JSON.stringify(content, null, 2));
}

export async function refreshTeacherWorkspacePlugins(courseId: string) {
  const course = await readServerCourse(courseId);
  if (!course) throw new Error('课程不存在');
  const workspace = path.join(COURSE_SPACES_DIR, 'agent-workspaces', courseId);
  await fs.mkdir(workspace, { recursive: true });
  const [jobs, artifacts, extractions, skills] = await Promise.all([
    listCourseJobs(courseId),
    listCourseArtifacts(courseId),
    Promise.all(course.materials.map((material) => readMaterialExtraction(material.id))),
    loadTeacherWorkspaceSkills(),
  ]);
  await Promise.all([
    writePlugin(workspace, 'course-structure', '课程结构、课时与实时统计', {
      course: {
        id: course.id,
        title: course.title,
        subject: course.subject,
        status: course.status,
      },
      modules: course.modules,
      statistics: {
        modules: course.modules.length,
        lessons: course.modules.reduce((sum, item) => sum + item.lessons.length, 0),
        materials: course.materials.length,
        readyMaterials: course.materials.filter((item) => item.status === 'ready').length,
        jobs: jobs.length,
        completedJobs: jobs.filter((item) => ['review', 'approved'].includes(item.status)).length,
        artifacts: artifacts.length,
      },
    }),
    writePlugin(workspace, 'course-materials', '教师上传材料的解析文本与可追溯原始页码', {
      materials: course.materials.map((material) => ({
        ...material,
        chunks:
          extractions.find((item) => item?.materialId === material.id)?.chunks.slice(0, 80) ?? [],
        formulas:
          extractions.find((item) => item?.materialId === material.id)?.formulas.slice(0, 80) ?? [],
      })),
    }),
    writePlugin(workspace, 'course-artifacts', '教学产物、审核状态和中间生成任务', {
      jobs: jobs.slice(0, 50),
      artifacts: artifacts.slice(0, 30).map((item) => ({
        id: item.id,
        type: item.type,
        title: item.title,
        status: item.status,
        content: item.content.slice(0, 12000),
        citations: item.citations,
      })),
    }),
    writePlugin(workspace, 'teacher-skills', '备课智能体可发现、可复用的标准技能', {
      skills,
    }),
  ]);
  return {
    workspace,
    course,
    jobs,
    artifacts,
    skills,
    extractions: extractions.filter((item): item is NonNullable<typeof item> => item !== null),
  };
}

function runHarness(input: { workspace: string; sessionId: string; prompt: string }) {
  const python = process.env.DEEPSEEK_HARNESS_PYTHON;
  const bridge =
    process.env.DEEPSEEK_HARNESS_BRIDGE ||
    path.join(process.cwd(), 'scripts', 'deepseek-harness-bridge.py');
  if (!python) return Promise.resolve<string | null>(null);
  return new Promise<string>((resolve, reject) => {
    const child = spawn(python, [bridge], {
      cwd: input.workspace,
      env: { ...process.env, DSH_WORKSPACE: input.workspace, DSH_SESSION_ID: input.sessionId },
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (data) => {
      stdout += String(data);
    });
    child.stderr.on('data', (data) => {
      stderr += String(data);
    });
    child.on('error', reject);
    child.on('close', (code) =>
      code === 0 && stdout.trim()
        ? resolve(stdout.trim())
        : reject(new Error(stderr.trim() || `Harness exited ${code}`)),
    );
    child.stdin.end(input.prompt);
  });
}

export async function runTeacherWorkspaceAgent(input: {
  courseId: string;
  sessionId: string;
  message: string;
  history?: ChatMessage[];
  attachments?: Array<{ name: string; mimeType: string; dataUrl: string }>;
  scope?: CourseArtifactJob['scope'];
  deepInteraction?: boolean;
}) {
  const context = await refreshTeacherWorkspacePlugins(input.courseId);
  const attachments = input.attachments ?? [];
  const workingLocation = (() => {
    const requestedScope = input.scope;
    if (!requestedScope || requestedScope.type === 'course') return context.course.title;
    if (requestedScope.type === 'module') {
      const courseModule = context.course.modules.find(
        (item) => item.id === requestedScope.moduleId,
      );
      return courseModule ? `${context.course.title} / ${courseModule.title}` : context.course.title;
    }
    for (const courseModule of context.course.modules) {
      const lesson = courseModule.lessons.find(
        (item) => item.id === requestedScope.lessonId,
      );
      if (lesson) return `${context.course.title} / ${courseModule.title} / ${lesson.title}`;
    }
    return context.course.title;
  })();
  if (attachments.length) {
    const attachmentDir = path.join(
      context.workspace,
      'attachments',
      safeSessionId(input.sessionId),
    );
    await fs.mkdir(attachmentDir, { recursive: true });
    await Promise.all(
      attachments.map(async (attachment) => {
        const encoded = attachment.dataUrl.match(
          /^data:image\/(?:png|jpeg|webp);base64,(.+)$/u,
        )?.[1];
        if (!encoded) throw new Error('截图格式不受支持，请上传 PNG、JPEG 或 WebP');
        const bytes = Buffer.from(encoded, 'base64');
        if (bytes.length > 5 * 1024 * 1024) throw new Error('单张截图不能超过 5MB');
        const extension =
          attachment.mimeType === 'image/png'
            ? 'png'
            : attachment.mimeType === 'image/webp'
              ? 'webp'
              : 'jpg';
        await fs.writeFile(path.join(attachmentDir, `${randomUUID()}.${extension}`), bytes);
      }),
    );
  }
  const pluginSummary = [
    `当前工作位置：${workingLocation}（可读取本课程全部文件夹；未明确其他范围时在此位置工作）`,
    `课程：${context.course.title}`,
    `结构：${context.course.modules.length} 个模块，${context.course.modules.reduce((sum, item) => sum + item.lessons.length, 0)} 个课时`,
    `材料：${context.course.materials.map((item) => `${item.name}(${item.status})`).join('、') || '暂无'}`,
    `任务：${context.jobs.length} 个；产物：${context.artifacts.length} 个`,
    `插件目录：${path.join(context.workspace, 'plugins')}`,
    `可用技能：${context.skills.map((skill) => skill.name).join('、') || '暂无'}`,
  ].join('\n');
  const pluginEvidence = context.extractions
    .flatMap((extraction) =>
      extraction.chunks
        .slice(0, 20)
        .map(
          (chunk) =>
            `[material:${extraction.materialId} page:${chunk.page}] ${chunk.text.replace(/\s+/g, ' ').slice(0, 600)}`,
        ),
    )
    .join('\n')
    .slice(0, 30000);
  const artifactEvidence = context.artifacts
    .slice(0, 12)
    .map(
      (item) =>
        `[artifact:${item.id} status:${item.status}] ${item.title}\n${item.content.slice(0, 1600)}`,
    )
    .join('\n\n')
    .slice(0, 18000);
  const skillContext = context.skills
    .map((skill) => `【${skill.name}】${skill.description}\n${skill.instructions}`)
    .join('\n\n');
  const interactionMode = input.deepInteraction
    ? '当前启用“深度交互”模式：先核对教师意图、当前范围和材料证据，再给出分步建议或可执行计划；存在歧义时主动询问。'
    : '';
  const prompt = `你是教师的私人课程操作智能体。你运行在 DeepSeek Harness 的课程隔离工作区中。\n已装入课程结构、材料、教学产物和可复用技能插件。回答课程统计时必须依据插件；引用材料时保留 [material:材料ID page:页码]；不要声称创建了未实际创建的产物。\n你已获准根据教师的明确指令启动教学大纲、教学计划、课件、讲稿、习题、评分量规等标准工作流。此类请求由平台操作路由执行并进入生成—审核—可视化流程，不要回复“无权生成”或要求教师改用聊天之外的入口。未被操作路由识别时，应提示教师明确产物类型和课程范围，不要在聊天消息中伪造已经落库的教学产物。\n${interactionMode}\n\n【课程结构与统计插件】\n${pluginSummary}\n\n【课程材料插件】\n${pluginEvidence || '暂无已解析材料'}\n\n【教学产物插件】\n${artifactEvidence || '暂无教学产物'}\n\n【可复用备课技能】\n${skillContext || '暂无'}\n\n最近对话：\n${(
    input.history ?? []
  )
    .slice(-8)
    .map((item) => `${item.role}: ${item.content}`)
    .join('\n')}\n\n教师：${input.message}`;
  if (!attachments.length)
    try {
      const harnessText = await runHarness({
        workspace: context.workspace,
        sessionId: safeSessionId(input.sessionId),
        prompt,
      });
      if (harnessText) return { text: harnessText, mode: 'deepseek-harness' as TeacherAgentMode };
    } catch (error) {
      console.warn(
        '[teacher-workspace] DeepSeek Harness unavailable, using compatible route:',
        error,
      );
    }
  const { model, thinkingConfig } = await resolveModel({ stage: 'generate-classroom' });
  const result = await callLLM(
    {
      model,
      system: '你是严谨、简洁的教师课程工作区智能体。请基于提供的课程插件摘要回答。',
      ...(attachments.length
        ? {
            messages: [
              {
                role: 'user' as const,
                content: [
                  {
                    type: 'text' as const,
                    text: `${prompt}\n\n请结合教师上传的截图识别界面、课件或教学内容，并回应教师要求。`,
                  },
                  ...attachments.map((attachment) => ({
                    type: 'image' as const,
                    image: attachment.dataUrl,
                    mediaType: attachment.mimeType,
                  })),
                ],
              },
            ],
          }
        : { prompt }),
    },
    'teacher-workspace-agent',
    { retries: 1 },
    thinkingConfig,
  );
  return {
    text: result.text.trim() || '暂时没有生成有效回复，请重试。',
    mode: 'deepseek-compatible' as TeacherAgentMode,
  };
}
