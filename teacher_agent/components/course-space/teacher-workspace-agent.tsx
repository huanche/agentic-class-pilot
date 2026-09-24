'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Bot,
  Brain,
  CheckCircle2,
  Circle,
  FolderOpen,
  Globe2,
  ImagePlus,
  LoaderCircle,
  MessageSquare,
  MessageSquarePlus,
  Play,
  Presentation,
  Send,
  ShieldCheck,
  X,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { SpeechButton } from '@/components/audio/speech-button';
import { InteractiveModeButton } from '@/components/generation/interactive-mode-button';
import type { CourseArtifactJob, CourseArtifactType, CourseSpace } from '@/lib/course-space';
import type { TeacherOperationPlan } from '@/lib/course-space/teacher-agent-intent';

type Message = { role: 'user' | 'assistant'; content: string; plan?: TeacherOperationPlan };
export type ScreenshotAttachment = { name: string; mimeType: string; dataUrl: string };
type SessionSummary = { id: string; title: string; updatedAt: number; status: string };

const actions: Array<{ type: CourseArtifactType; label: string }> = [
  { type: 'course-outline', label: '教学大纲' },
  { type: 'module-plan', label: '教学计划' },
  { type: 'lesson-courseware', label: '课件' },
  { type: 'narration', label: '讲稿' },
  { type: 'exercise-set', label: '习题' },
  { type: 'assessment-rubric', label: '评分量规' },
];

export function TeacherWorkspaceAgent({
  course,
  activeScope,
  onGenerate,
  onOperationComplete,
  onOpenKnowledgeGraph,
  embedded = false,
  externalPrompt,
}: {
  course: CourseSpace;
  activeScope: CourseArtifactJob['scope'];
  onGenerate: (type: CourseArtifactType, scope?: CourseArtifactJob['scope']) => void;
  onOperationComplete?: () => void | Promise<void>;
  onOpenKnowledgeGraph?: () => void;
  embedded?: boolean;
  externalPrompt?: { id: number; text: string; attachments?: ScreenshotAttachment[] };
}) {
  const initialMessage = useMemo<Message>(() => ({
    role: 'assistant',
    content: `你好，我是“${course.title}”的课程操作智能体。课程材料、结构、知识图谱与中间产物已作为插件接入。我可以按你的要求启动教学大纲、教学计划、课件、讲稿、习题和评分量规工作，也可以创建、移动或删除课程文件。生成任务会直接进入标准生成—审核—可视化流程；结构变更与删除操作会先提交计划供你确认。`,
  }), [course.title]);
  const [sessionId, setSessionId] = useState(() => `teacher-${course.id}-default`);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      content: `你好，我是“${course.title}”的课程操作智能体。课程材料、结构、知识图谱与中间产物已作为插件接入。我可以按你的要求启动教学大纲、教学计划、课件、讲稿、习题和评分量规工作，也可以创建、移动或删除课程文件。生成任务会直接进入标准生成—审核—可视化流程；结构变更与删除操作会先提交计划供你确认。`,
    },
  ]);
  const [input, setInput] = useState('');
  const voiceInputBaseRef = useRef<string | null>(null);
  const [attachments, setAttachments] = useState<ScreenshotAttachment[]>([]);
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState('DeepSeek Harness');
  const [deepInteraction, setDeepInteraction] = useState(false);
  const conversationEndRef = useRef<HTMLDivElement>(null);
  const loadSessions = useCallback(async () => {
    const response = await fetch(`/api/course-space/${course.id}/agent?list=1`, { cache: 'no-store' });
    const data = await response.json() as { sessions?: SessionSummary[] };
    if (response.ok) setSessions(data.sessions ?? []);
  }, [course.id]);
  const workingLocation = useMemo(() => {
    if (activeScope.type === 'course') return course.title;
    if (activeScope.type === 'module') {
      const courseModule = course.modules.find((item) => item.id === activeScope.moduleId);
      return courseModule ? `${course.title} / ${courseModule.title}` : course.title;
    }
    for (const courseModule of course.modules) {
      const lesson = courseModule.lessons.find((item) => item.id === activeScope.lessonId);
      if (lesson) return `${course.title} / ${courseModule.title} / ${lesson.title}`;
    }
    return course.title;
  }, [activeScope, course]);
  const accessibleFolderCount = useMemo(
    () =>
      course.modules.length +
      course.modules.reduce((count, courseModule) => count + courseModule.lessons.length, 0),
    [course.modules],
  );
  const addImageFiles = (incoming: File[]) => {
    const files = incoming
      .filter(
        (file) =>
          ['image/png', 'image/jpeg', 'image/webp'].includes(file.type) &&
          file.size <= 5 * 1024 * 1024,
      )
      .slice(0, Math.max(0, 3 - attachments.length));
    for (const file of files) {
      const reader = new FileReader();
      reader.onload = () => {
        const dataUrl = reader.result;
        if (typeof dataUrl !== 'string') return;
        setAttachments((items) =>
          [
            ...items,
            {
              name: file.name || `粘贴截图-${Date.now()}.png`,
              mimeType: file.type,
              dataUrl,
            },
          ].slice(0, 3),
        );
      };
      reader.readAsDataURL(file);
    }
  };
  useEffect(() => {
    setSessionId(`teacher-${course.id}-default`);
    void loadSessions().catch(() => undefined);
  }, [course.id, loadSessions]);
  useEffect(() => {
    let active = true;
    setMessages([initialMessage]);
    void fetch(`/api/course-space/${course.id}/agent?sessionId=${encodeURIComponent(sessionId)}`, {
      cache: 'no-store',
    })
      .then((response) => response.json())
      .then((data: { messages?: Message[] }) => {
        if (active && data.messages?.length) setMessages(data.messages);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [course.id, initialMessage, sessionId]);
  useEffect(() => {
    conversationEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, loading]);
  const send = async (preset?: string) => {
    const content = (preset ?? input).trim();
    if (!content || loading) return;
    const next = [...messages, { role: 'user' as const, content }];
    setMessages(next);
    setInput('');
    setLoading(true);
    try {
      const response = await fetch(`/api/course-space/${course.id}/agent`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          sessionId,
          message: content,
          history: messages,
          attachments: externalPrompt?.attachments ?? attachments,
          scope: activeScope,
          deepInteraction,
        }),
      });
      const data = await response.json();
      if (!response.ok || data.success === false) throw new Error(data.error || '智能体响应失败');
      let responseText = data.text;
      let responsePlan = data.plan as TeacherOperationPlan | undefined;
      if (
        responsePlan?.action &&
        responsePlan.status === 'planned' &&
        !responsePlan.requiresConfirmation
      ) {
        const operationResponse = await fetch(`/api/course-space/${course.id}/agent/operations`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ plan: responsePlan }),
        });
        const operation = await operationResponse.json();
        if (!operationResponse.ok || operation.success === false)
          throw new Error(operation.error || '启动标准生成工作流失败');
        responsePlan = operation.plan;
        responseText =
          operation.plan.result ||
          (operation.dispatch === 'artifact-workflow'
            ? '已根据教师指令启动标准生成工作流。生成结果将进入审核与可视化页面。'
            : '已根据教师指令完成课程操作。');
        if (
          operation.dispatch === 'artifact-workflow' &&
          operation.plan.action?.type === 'generate-artifact'
        )
          onGenerate(operation.plan.action.artifactType, operation.plan.action.scope);
        else await onOperationComplete?.();
      }
      setMessages([...next, { role: 'assistant', content: responseText, plan: responsePlan }]);
      void loadSessions().catch(() => undefined);
      setAttachments([]);
      setMode(
        data.mode === 'course-operator'
          ? '课程操作智能体'
          : data.mode === 'deepseek-harness'
            ? 'DeepSeek Harness'
            : 'DeepSeek 兼容模式',
      );
    } catch (error) {
      setMessages([
        ...next,
        {
          role: 'assistant',
          content: `暂时无法完成：${error instanceof Error ? error.message : String(error)}`,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };
  const lastExternalPromptId = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (!externalPrompt || loading || lastExternalPromptId.current === externalPrompt.id) return;
    lastExternalPromptId.current = externalPrompt.id;
    void send(externalPrompt.text);
  }, [externalPrompt, loading]); // External prompts are one-shot commands from the shared workbench composer.
  const executePlan = async (messageIndex: number, plan: TeacherOperationPlan) => {
    if (loading) return;
    setLoading(true);
    try {
      const response = await fetch(`/api/course-space/${course.id}/agent/operations`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ plan }),
      });
      const data = await response.json();
      if (!response.ok || data.success === false) throw new Error(data.error || '执行课程操作失败');
      setMessages((items) =>
        items.map((item, index) =>
          index === messageIndex
            ? {
                ...item,
                content:
                  data.plan.result ||
                  (data.dispatch === 'artifact-workflow'
                    ? '计划已确认，正在进入标准生成工作流。'
                    : '操作已完成。'),
                plan: data.plan,
              }
            : item,
        ),
      );
      if (data.dispatch === 'artifact-workflow' && data.plan.action?.type === 'generate-artifact')
        onGenerate(data.plan.action.artifactType, data.plan.action.scope);
      else await onOperationComplete?.();
    } catch (error) {
      setMessages((items) => [
        ...items,
        {
          role: 'assistant',
          content: `操作执行失败：${error instanceof Error ? error.message : String(error)}`,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };
  const startNewSession = () => {
    const nextSessionId = `teacher-${course.id}-${Date.now().toString(36)}`;
    setSessionId(nextSessionId);
    setMessages([initialMessage]);
    setInput('');
    setAttachments([]);
  };
  return (
    <div className={`flex h-full flex-col overflow-hidden rounded-2xl border border-slate-200/80 bg-white/90 shadow-sm backdrop-blur-xl ${embedded ? 'min-h-0' : 'min-h-[600px]'}`}>
      {!embedded && <div className="flex items-center justify-between border-b border-slate-100 bg-white/80 px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="rounded-xl bg-gradient-to-br from-[#B00055]/15 to-[#B00055]/5 p-2.5 text-[#B00055]">
            <Bot className="size-5" />
          </div>
          <div>
            <h3 className="font-semibold">备课工作智能体</h3>
            <p className="text-xs text-muted-foreground">
              DeepSeek Harness · 课程材料、结构、知识图谱与产物已连接
            </p>
          </div>
        </div>
        <span className="rounded-full border border-emerald-100 bg-emerald-50 px-2.5 py-1 text-[11px] text-emerald-700">
          {mode}
        </span>
      </div>}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-slate-100 bg-[#fff8fb] px-5 py-3 text-xs">
        <div className="flex min-w-0 items-center gap-2 text-slate-700">
          <FolderOpen className="size-4 shrink-0 text-[#B00055]" />
          <span className="shrink-0 font-medium">当前工作位置</span>
          <span className="truncate text-[#8F0046]">{workingLocation}</span>
        </div>
        <div className="ml-auto flex items-center gap-1.5 text-slate-500">
          <span className="mr-2 rounded-full border border-emerald-100 bg-emerald-50 px-2 py-1 text-[10px] font-medium text-emerald-700">
            {mode}
          </span>
          <ShieldCheck className="size-4 text-emerald-600" />
          可访问本课程全部 {accessibleFolderCount} 个文件夹
        </div>
      </div>
      <div className="flex min-h-0 flex-1">
        <aside className="flex w-64 shrink-0 flex-col border-r border-slate-100 bg-slate-50/80">
          <div className="border-b border-slate-100 p-3">
            <Button type="button" variant="outline" className="w-full justify-start rounded-xl bg-white" onClick={startNewSession}>
              <MessageSquarePlus className="mr-2 size-4 text-[#B00055]" />
              新备课会话
            </Button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            <p className="px-2 pb-2 pt-1 text-[10px] font-medium uppercase tracking-[.14em] text-slate-400">历史会话</p>
            <div className="space-y-1">
              {sessions.map((session) => (
                <button key={session.id} type="button" onClick={() => setSessionId(session.id)} className={`flex w-full items-start gap-2 rounded-xl px-3 py-2.5 text-left transition ${sessionId === session.id ? 'bg-[#B00055]/10 text-[#8F0046]' : 'text-slate-600 hover:bg-white hover:text-slate-900'}`}>
                  <MessageSquare className="mt-0.5 size-3.5 shrink-0" />
                  <span className="min-w-0">
                    <span className="block truncate text-xs font-medium">{session.title || '新备课会话'}</span>
                    <span className="mt-1 block text-[10px] text-slate-400">{new Date(session.updatedAt).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
                  </span>
                </button>
              ))}
              {!sessions.length && <p className="px-3 py-5 text-xs leading-5 text-slate-400">发送第一条消息后，会话将保存在这里。</p>}
            </div>
          </div>
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto bg-[radial-gradient(circle_at_top_left,rgba(176,0,85,0.06),transparent_38%),#fbfcfe] p-5">
        {messages.map((message, index) => (
          <div
            key={index}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div className={`max-w-[86%] ${message.role === 'user' ? '' : 'space-y-2'}`}>
              <div
                className={`whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-6 ${message.role === 'user' ? 'rounded-br-md bg-[#B00055] text-white shadow-sm' : 'rounded-bl-md border border-slate-200 bg-white text-slate-700 shadow-sm'}`}
              >
                {message.content}
              </div>
              {message.plan && (
                <div className="rounded-2xl border border-[#B00055]/15 bg-white p-4 shadow-sm">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-semibold text-slate-900">{message.plan.title}</p>
                      <p className="mt-1 text-xs leading-5 text-slate-500">
                        {message.plan.summary}
                      </p>
                    </div>
                    <span className="shrink-0 rounded-full bg-[#B00055]/8 px-2 py-1 text-[10px] text-[#B00055]">
                      {message.plan.status === 'planned'
                        ? '待执行'
                        : message.plan.status === 'completed'
                          ? '已完成'
                          : '已暂停'}
                    </span>
                  </div>
                  <div className="mt-3 space-y-2">
                    {message.plan.steps.map((step) => (
                      <div key={step.id} className="flex items-center gap-2 text-xs text-slate-600">
                        {step.status === 'completed' ? (
                          <CheckCircle2 className="size-4 text-emerald-500" />
                        ) : (
                          <Circle
                            className={`size-4 ${step.status === 'blocked' ? 'text-amber-500' : 'text-slate-300'}`}
                          />
                        )}
                        <span>{step.label}</span>
                        <code className="ml-auto text-[10px] text-slate-400">{step.tool}</code>
                      </div>
                    ))}
                  </div>
                  {message.plan.result && (
                    <p className="mt-3 rounded-xl bg-slate-50 p-3 text-xs leading-5 text-slate-700">
                      {message.plan.result}
                    </p>
                  )}
                  {message.plan.requiresConfirmation && message.plan.status === 'planned' && (
                    <Button
                      size="sm"
                      variant={
                        message.plan.action?.type.startsWith('delete') ? 'destructive' : 'default'
                      }
                      className="mt-3 rounded-full"
                      onClick={() => void executePlan(index, message.plan!)}
                    >
                      <Play className="mr-1 size-3.5" />
                      {message.plan.action?.type.startsWith('delete') ? '确认删除' : '确认执行'}
                    </Button>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <LoaderCircle className="size-4 animate-spin" />
            正在形成操作计划或调用课程工具…
          </div>
        )}
        <div ref={conversationEndRef} />
      </div>
      <div className="border-t border-slate-100 bg-white/90 p-4">
        {!embedded && <div className="mb-3 flex flex-wrap gap-2">
          {actions.map((item) => (
              <button key={item.type} onClick={() => onGenerate(item.type)} className="rounded-full border border-[#B00055]/20 bg-[#B00055]/5 px-3 py-1.5 text-xs text-[#B00055] hover:bg-[#B00055]/10">{item.label}</button>
            ))}
        </div>}
        {attachments.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {attachments.map((attachment, index) => (
              <div
                key={`${attachment.name}-${index}`}
                className="relative overflow-hidden rounded-xl border border-[#B00055]/15 bg-white p-1 shadow-sm"
              >
                <img
                  src={attachment.dataUrl}
                  alt={attachment.name}
                  className="h-16 w-24 rounded-lg object-cover"
                />
                <button
                  type="button"
                  aria-label={`移除截图 ${attachment.name}`}
                  onClick={() =>
                    setAttachments((items) => items.filter((_, itemIndex) => itemIndex !== index))
                  }
                  className="absolute right-1 top-1 rounded-full bg-slate-900/70 p-1 text-white"
                >
                  <X className="size-3" />
                </button>
              </div>
            ))}
          </div>
        )}
        <div className="overflow-hidden rounded-2xl border border-[#B00055]/20 bg-slate-50/75 shadow-sm transition focus-within:border-[#B00055]/40 focus-within:ring-2 focus-within:ring-[#B00055]/10">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPaste={(event) => {
              const images = Array.from(event.clipboardData.items)
                .filter((item) => item.kind === 'file' && item.type.startsWith('image/'))
                .map((item) => item.getAsFile())
                .filter((file): file is File => Boolean(file));
              if (!images.length) return;
              event.preventDefault();
              addImageFiles(images);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            className="min-h-24 w-full resize-none bg-transparent px-4 pb-2 pt-4 text-sm leading-6 outline-none"
            placeholder="例如：把第一周内容移到第二周、删除空课时文件夹，或生成本周课件…"
          />
          <div className="flex flex-wrap items-center gap-2 px-3 pb-3">
            <button type="button" className="inline-flex h-8 items-center gap-1.5 rounded-full border border-violet-200 bg-violet-50 px-2.5 text-xs font-medium text-violet-700" title="使用高强度推理">
              <Brain className="size-3.5" />
              high
            </button>
            <span className="h-4 w-px bg-slate-200" />
            <label className="grid size-8 shrink-0 cursor-pointer place-items-center rounded-full border border-slate-200 bg-white text-slate-500 hover:border-[#B00055]/30 hover:text-[#B00055]" title="上传或粘贴截图">
              <ImagePlus className="size-3.5" />
              <input type="file" accept="image/png,image/jpeg,image/webp" multiple className="sr-only" onChange={(event) => { addImageFiles(Array.from(event.target.files ?? [])); event.target.value = ''; }}/>
            </label>
            <button type="button" className="grid size-8 place-items-center rounded-full border border-slate-200 bg-white text-slate-400" title="课程材料与已解析网页上下文">
              <Globe2 className="size-3.5" />
            </button>
            <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
              <button type="button" onClick={() => onGenerate('lesson-courseware', activeScope)} className="inline-flex h-8 items-center gap-1.5 rounded-full border border-[#B00055]/25 bg-[#B00055]/5 px-3 text-xs font-medium text-[#B00055] hover:bg-[#B00055]/10">
                <Presentation className="size-3.5" />讲师 PPT
              </button>
              <button type="button" onClick={onOpenKnowledgeGraph} className="inline-flex h-8 items-center gap-1.5 rounded-full border border-[#B00055]/25 bg-[#B00055]/5 px-3 text-xs font-medium text-[#B00055] hover:bg-[#B00055]/10">
                <Brain className="size-3.5" />知识图谱
              </button>
              <InteractiveModeButton pressed={deepInteraction} label="深度交互" onPressedChange={setDeepInteraction} />
              <SpeechButton size="md" disabled={loading} continuous onInterimTranscription={(text) => setInput((current) => { if (voiceInputBaseRef.current === null) voiceInputBaseRef.current = current; const base = voiceInputBaseRef.current; return `${base}${base.trim() ? ' ' : ''}${text}`; })} onTranscription={(text) => setInput((current) => { const base = voiceInputBaseRef.current; voiceInputBaseRef.current = null; const stableBase = base ?? current; return `${stableBase}${stableBase.trim() ? ' ' : ''}${text}`; })} className="size-8 rounded-full hover:bg-white hover:text-[#B00055]" />
              <Button size="icon" className="size-9 shrink-0 rounded-full" disabled={loading || !input.trim()} onClick={() => void send()} title="发送消息">
                <Send className="size-4" />
              </Button>
            </div>
          </div>
        </div>
        <p className="mt-2 text-[11px] text-muted-foreground">
          麦克风开启后会边听边显示文字，再次点击停止 · 可上传或 Ctrl+V 粘贴截图 · Enter 发送
        </p>
      </div>
        </div>
      </div>
    </div>
  );
}
