'use client';

import { ArrowLeft, Clock3 } from 'lucide-react';
import { useI18n } from '@/lib/hooks/use-i18n';
import { useRouter } from 'next/navigation';
import type { StageMode } from '@/lib/types/stage';
import { HeaderControls } from './stage/header-controls';

interface HeaderProps {
  readonly currentSceneTitle: string;
  readonly mode?: StageMode;
  readonly canEdit?: boolean;
  readonly onToggleEditMode?: () => void;
  readonly totalDurationMinutes?: number;
}

export function Header({
  currentSceneTitle,
  mode,
  canEdit,
  onToggleEditMode,
  totalDurationMinutes,
}: HeaderProps) {
  const { t } = useI18n();
  const router = useRouter();

  return (
    <>
      <header className="h-20 px-8 flex items-center justify-between z-10 bg-transparent gap-4">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <button
            onClick={() => router.push('/')}
            className="shrink-0 p-2 rounded-lg text-gray-400 dark:text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-700 dark:hover:text-gray-300 transition-colors"
            title={t('generation.backToHome')}
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          {/* Title block — hidden when `mode === 'edit'`. Header lives
              inside `PlaybackChromeRoot`, which is unmounted by `Stage`
              once mode flips to 'edit', so in steady state this branch
              is always taken. The guard exists for the ~280ms
              AnimatePresence exit window where the playback chrome
              is still rendering its exit animation while `mode` has
              already flipped — without the guard, this title would
              briefly stack on top of the incoming EditChromeRoot's
              CommandBar title during the cross-fade. */}
          {mode !== 'edit' && (
            <div className="flex flex-col min-w-0">
              <span className="text-[10px] uppercase tracking-widest font-bold text-gray-400 dark:text-gray-500 mb-0.5">
                {t('stage.currentScene')}
              </span>
              <h1
                className="text-xl font-bold text-gray-800 dark:text-gray-200 tracking-tight truncate"
                suppressHydrationWarning
              >
                {currentSceneTitle || t('common.loading')}
              </h1>
            </div>
          )}
          {mode !== 'edit' && totalDurationMinutes != null && (
            <div className="ml-2 flex shrink-0 items-center gap-1.5 rounded-full border border-violet-100 bg-violet-50/80 px-3 py-1.5 text-xs font-medium text-violet-700 dark:border-violet-800/60 dark:bg-violet-950/30 dark:text-violet-300">
              <Clock3 className="h-3.5 w-3.5" />
              预计 {Math.round(totalDurationMinutes)} 分钟
            </div>
          )}
        </div>

        <HeaderControls mode={mode} canEdit={canEdit} onToggleEditMode={onToggleEditMode} />
      </header>
    </>
  );
}
