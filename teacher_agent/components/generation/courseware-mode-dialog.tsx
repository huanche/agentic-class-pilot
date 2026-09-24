'use client';

import { BadgeCheck, Presentation, Sparkles } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';
import type { CoursewareConversionMode } from '@/lib/learning-skills/courseware-mode';

interface CoursewareModeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (mode: CoursewareConversionMode) => void;
  sourceLabel?: 'PPTX' | 'PPT / PPTX' | 'PDF / PPTX';
  faithfulDisabledReason?: string;
}

const choices: Array<{
  mode: CoursewareConversionMode;
  title: string;
  badge: string;
  description: string;
  details: string[];
  icon: typeof Presentation;
  accent: string;
}> = [
  {
    mode: 'faithful',
    title: '高保真还原',
    badge: '原稿优先',
    description: '保留原页序与视觉表达，在原稿上增加自动讲解和播放动作。',
    details: [
      'PPTX 保留原始画布与页数',
      '逐页配音、高亮、聚焦和激光笔',
      '适合已有成熟课件直接授课',
    ],
    icon: Presentation,
    accent:
      'border-blue-200 hover:border-blue-400 hover:bg-blue-50/70 dark:border-blue-900 dark:hover:bg-blue-950/30',
  },
  {
    mode: 'learning-skills-enhanced',
    title: 'Learning Skills 教学增强',
    badge: '教学设计优先',
    description: '理解原稿后重构教学路径，补齐目标、互动、分层支持和学习检测。',
    details: [
      '按学科和年级选择教学法',
      '加入 UDL 分层、形成性检测与退出任务',
      '允许调整页数、版式和教学顺序',
    ],
    icon: Sparkles,
    accent:
      'border-violet-200 hover:border-violet-400 hover:bg-violet-50/70 dark:border-violet-900 dark:hover:bg-violet-950/30',
  },
];

export function CoursewareModeDialog({
  open,
  onOpenChange,
  onSelect,
  sourceLabel = 'PDF / PPTX',
  faithfulDisabledReason,
}: CoursewareModeDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="text-xl">选择课件转换路径</DialogTitle>
          <DialogDescription>
            已检测到 {sourceLabel} 教学材料。两条路径都会生成可自动播放、带配音和课堂动作的 MENTRA
            课件。
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3 md:grid-cols-2">
          {choices.map((choice) => {
            const Icon = choice.icon;
            const disabled = choice.mode === 'faithful' && Boolean(faithfulDisabledReason);
            return (
              <button
                key={choice.mode}
                type="button"
                onClick={() => onSelect(choice.mode)}
                disabled={disabled}
                className={cn(
                  'group rounded-2xl border bg-background p-5 text-left transition-all hover:-translate-y-0.5 hover:shadow-lg',
                  choice.accent,
                  disabled && 'cursor-not-allowed opacity-50 hover:translate-y-0 hover:shadow-none',
                )}
              >
                <div className="mb-4 flex items-center justify-between gap-3">
                  <span className="flex size-10 items-center justify-center rounded-xl bg-muted text-foreground group-hover:bg-background">
                    <Icon className="size-5" />
                  </span>
                  <span className="rounded-full bg-muted px-2.5 py-1 text-[11px] font-medium text-muted-foreground">
                    {choice.badge}
                  </span>
                </div>
                <h3 className="text-base font-semibold">{choice.title}</h3>
                <p className="mt-2 min-h-10 text-xs leading-relaxed text-muted-foreground">
                  {choice.description}
                </p>
                <ul className="mt-4 space-y-2">
                  {choice.details.map((detail) => (
                    <li key={detail} className="flex items-start gap-2 text-xs text-foreground/80">
                      <BadgeCheck className="mt-0.5 size-3.5 shrink-0 text-emerald-500" />
                      <span>{detail}</span>
                    </li>
                  ))}
                </ul>
                {disabled && <p className="mt-3 text-xs font-medium text-amber-700">{faithfulDisabledReason}</p>}
              </button>
            );
          })}
        </div>

        <p className="text-[11px] leading-relaxed text-muted-foreground">
          提示：PDF 的高保真程度取决于文档解析器；需要严格保留视觉画布时，优先上传原始 PPTX。
        </p>
      </DialogContent>
    </Dialog>
  );
}
