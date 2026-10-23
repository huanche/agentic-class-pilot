'use client';

import { useState } from 'react';
import { FileText, LoaderCircle, Presentation } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  CourseDurationInput,
  courseDurationInputError,
} from '@/components/generation/course-duration-input';
import {
  coursewareScopeContext,
  defaultCoursewareMaterialIds,
  faithfulCoursewareDisabledReason,
  type CoursewareGenerationOptions,
} from '@/lib/course-space/courseware-generation';
import { DEFAULT_TARGET_MINUTES } from '@/lib/generation/course-duration';
import type { CourseArtifactJob, CourseSpace } from '@/lib/course-space';
import type { CoursewareConversionMode } from '@/lib/learning-skills/courseware-mode';

const STATUS_LABELS = {
  ready: '已解析',
  uploaded: '待解析',
  parsing: '解析中',
  'pending-review': '待审核',
  failed: '解析失败',
};

export function CoursewareGenerationDialog({
  course,
  scope,
  initialInstruction,
  generationLocked,
  onClose,
  onParse,
  onSubmit,
}: {
  course: CourseSpace;
  scope: CourseArtifactJob['scope'];
  initialInstruction?: string;
  generationLocked: boolean;
  onClose: () => void;
  onParse: (materialId: string) => Promise<void>;
  onSubmit: (options: CoursewareGenerationOptions) => Promise<void>;
}) {
  const context = (() => {
    try {
      return coursewareScopeContext(course, scope);
    } catch {
      return undefined;
    }
  })();
  const [materialIds, setMaterialIds] = useState(() =>
    context ? defaultCoursewareMaterialIds(course, scope) : [],
  );
  const [targetDurationMinutes, setTargetDurationMinutes] = useState(
    String(DEFAULT_TARGET_MINUTES),
  );
  const [instruction, setInstruction] = useState(initialInstruction ?? '');
  const [conversionMode, setConversionMode] = useState<CoursewareConversionMode>(
    'learning-skills-enhanced',
  );
  const [busy, setBusy] = useState(false);
  const [parsingId, setParsingId] = useState('');
  const [error, setError] = useState('');
  const selectedIds = materialIds.filter((id) =>
    course.materials.some((item) => item.id === id && item.status === 'ready'),
  );
  const faithfulReason = faithfulCoursewareDisabledReason(course, selectedIds);
  const submit = async () => {
    if (
      !context ||
      busy ||
      generationLocked ||
      !selectedIds.length ||
      (conversionMode === 'faithful' && Boolean(faithfulReason)) ||
      courseDurationInputError(targetDurationMinutes)
    )
      return;
    setBusy(true);
    setError('');
    try {
      await onSubmit({
        materialIds: selectedIds,
        targetDurationMinutes,
        instruction,
        conversionMode,
      });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) onClose();
      }}
    >
      <DialogContent
        className="flex max-h-[90vh] max-w-[calc(100%-2rem)] flex-col gap-0 overflow-hidden p-0 sm:max-w-3xl"
        showCloseButton={!busy}
      >
        <DialogHeader className="shrink-0 border-b px-6 pb-4 pt-5 pr-12">
          <div className="mb-1 flex items-center gap-2 text-[#B00055]">
            <Presentation className="size-5" />
            <DialogTitle className="text-lg font-semibold">生成课件</DialogTitle>
          </div>
          <DialogDescription>
            选择资料和讲解时长，先生成大纲供你审核。无需重复上传或发送生成指令。
          </DialogDescription>
        </DialogHeader>
        <div className="grid min-h-0 gap-4 overflow-y-auto px-6 py-4 sm:grid-cols-2">
          <div className="rounded-xl border border-[#B00055]/15 bg-[#fff8fb] px-4 py-3 sm:col-span-2">
            <p className="text-xs text-[#8F0046]">本次生成位置</p>
            <p className="mt-1 text-sm font-medium text-slate-800">
              {context?.path || '所选课时已不存在，请关闭后重新选择。'}
            </p>
          </div>
          <fieldset disabled={busy} className="min-w-0 space-y-2">
            <legend className="mb-2 text-sm font-medium">
              已有课程资料{' '}
              <span className="font-normal text-slate-500">· 已选 {selectedIds.length} 份</span>
            </legend>
            <p className="text-xs leading-5 text-slate-500">
              优先勾选本课时关联资料；未关联且有多份资料时，请手动选择。仅使用本次勾选的内容。
            </p>
            <div className="max-h-52 divide-y overflow-y-auto rounded-lg border border-slate-200">
              {course.materials.map((material) => (
                <div key={material.id} className="flex items-center gap-3 px-3 py-2.5">
                  <label
                    className={`flex min-w-0 flex-1 items-center gap-3 text-sm ${material.status === 'ready' ? 'cursor-pointer' : 'text-slate-400'}`}
                  >
                    <input
                      type="checkbox"
                      className="size-4 accent-[#B00055]"
                      checked={selectedIds.includes(material.id)}
                      disabled={material.status !== 'ready'}
                      onChange={(event) =>
                        setMaterialIds((ids) =>
                          event.target.checked
                            ? [...ids, material.id]
                            : ids.filter((id) => id !== material.id),
                        )
                      }
                    />
                    <FileText className="size-4 shrink-0 text-slate-400" />
                    <span className="min-w-0 break-all">{material.name}</span>
                    <span className="ml-auto shrink-0 text-xs text-slate-500">
                      {STATUS_LABELS[material.status]}
                    </span>
                  </label>
                  {['uploaded', 'failed'].includes(material.status) && (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={Boolean(parsingId)}
                      onClick={async () => {
                        setParsingId(material.id);
                        setError('');
                        try {
                          await onParse(material.id);
                        } catch (e) {
                          setError(e instanceof Error ? e.message : String(e));
                        } finally {
                          setParsingId('');
                        }
                      }}
                    >
                      {parsingId === material.id
                        ? '启动中…'
                        : material.status === 'failed'
                          ? '重新解析'
                          : '解析资料'}
                    </Button>
                  )}
                </div>
              ))}
              {!course.materials.length && (
                <p className="px-4 py-5 text-sm text-slate-500">
                  课程中还没有资料，请先在左侧“课程资料”上传一次，再从这里选择。
                </p>
              )}
            </div>
            {!selectedIds.length && (
              <p className="text-xs text-amber-700">
                请选择至少一份已解析的资料；解析完成后即可勾选。
              </p>
            )}
          </fieldset>
          <div className="min-w-0 space-y-4">
            <fieldset disabled={busy} className="space-y-2">
              <legend className="mb-2 text-sm font-medium">生成模式</legend>
              {(
                [
                  ['faithful', '高保真还原', '保留 PPTX 原始画面和页序，补充讲解与配音。'],
                  [
                    'learning-skills-enhanced',
                    'AI 增强',
                    '依据资料重新组织讲解、画面、互动和测验。',
                  ],
                ] as const
              ).map(([mode, title, description]) => (
                <label
                  key={mode}
                  className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 ${conversionMode === mode ? 'border-[#B00055] bg-[#fff8fb]' : 'border-slate-200'} ${mode === 'faithful' && faithfulReason ? 'cursor-not-allowed opacity-60' : ''}`}
                >
                  <input
                    type="radio"
                    name="courseware-mode"
                    value={mode}
                    checked={conversionMode === mode}
                    disabled={mode === 'faithful' && Boolean(faithfulReason)}
                    onChange={() => setConversionMode(mode)}
                    className="mt-1 accent-[#B00055]"
                  />
                  <span className="min-w-0 text-sm font-medium">
                    {title}
                    <span className="mt-1 block text-xs font-normal leading-5 text-slate-500">
                      {description}
                    </span>
                  </span>
                </label>
              ))}
              {faithfulReason && (
                <p className="text-xs leading-5 text-slate-500">{faithfulReason}</p>
              )}
            </fieldset>
            <fieldset disabled={busy}>
              <CourseDurationInput
                value={targetDurationMinutes}
                onChange={setTargetDurationMinutes}
              />
            </fieldset>
            <label className="space-y-2 text-sm font-medium">
              <span>
                补充要求 <span className="font-normal text-slate-500">（选填）</span>
              </span>
              <textarea
                aria-label="课件补充要求"
                value={instruction}
                disabled={busy}
                onChange={(event) => setInstruction(event.target.value)}
                placeholder="例如：面向零基础，增加一个循环示例，重点解释常见错误。"
                rows={3}
                className="mt-2 block w-full resize-y rounded-lg border border-slate-200 px-3 py-2 text-sm font-normal leading-6 outline-none focus:border-[#B00055]"
              />
            </label>
          </div>
          {(error || generationLocked || !context) && (
            <p role="alert" className="text-sm text-red-600 sm:col-span-2">
              {error ||
                (!context
                  ? '所选课时已不存在，请关闭后重新选择。'
                  : '当前有课件任务正在生成，请完成或取消后再试。')}
            </p>
          )}
        </div>
        <DialogFooter className="shrink-0 border-t px-6 py-4">
          <Button variant="outline" disabled={busy} onClick={onClose}>
            取消
          </Button>
          <Button
            disabled={
              busy ||
              generationLocked ||
              !context ||
              !selectedIds.length ||
              (conversionMode === 'faithful' && Boolean(faithfulReason)) ||
              Boolean(courseDurationInputError(targetDurationMinutes))
            }
            onClick={() => void submit()}
            className="bg-[#B00055] hover:bg-[#8F0046]"
          >
            {busy && <LoaderCircle className="mr-2 size-4 animate-spin" />}
            {busy ? '正在读取资料…' : '生成课件大纲'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
