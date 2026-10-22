'use client';

import { useEffect, useRef } from 'react';
import { useComposerRuntime } from '@assistant-ui/react';

/** Keep unfinished feedback with its page when the teacher browses the deck. */
export function PageReviewDraft({ sceneId }: { sceneId?: string }) {
  const composer = useComposerRuntime();
  const drafts = useRef(new Map<string, string>());
  const previous = useRef(sceneId);
  useEffect(() => {
    if (previous.current === sceneId) return;
    if (previous.current) drafts.current.set(previous.current, composer.getState().text);
    composer.setText(sceneId ? (drafts.current.get(sceneId) ?? '') : '');
    previous.current = sceneId;
  }, [sceneId, composer]);
  return null;
}

export function PageReviewHints({ sceneType, canSend }: { sceneType?: string; canSend: boolean }) {
  const composer = useComposerRuntime();
  const suggestions =
    sceneType === 'interactive'
      ? [
          [
            '修改互动内容',
            '请只修改当前页的互动内容，按以下建议调整，并同步检查本页讲解与聚焦：\n',
          ],
          ['修复互动问题', '请检查并修复当前互动页的问题：\n'],
        ]
      : [
          ['重新生成本页', '请只重新生成当前页的画面、讲解和聚焦动作，按以下建议调整：\n'],
          ['只调整讲解', '请保留当前页画面，只重新生成本页讲解和对应的聚焦动作，要求：\n'],
        ];
  return (
    <div className="mx-auto mt-8 flex max-w-[268px] flex-col">
      <p className="text-sm font-medium text-foreground">这一页哪里需要改进？</p>
      <p className="mt-2 text-xs leading-6 text-muted-foreground">
        查看画面与下方讲解稿，写下具体建议。修改仅针对提交时选中的这一页。
      </p>
      {canSend ? (
        <>
          <div className="mt-4 flex flex-wrap gap-2">
            {suggestions.map(([label, prompt]) => (
              <button
                key={label}
                type="button"
                onClick={() => composer.setText(prompt)}
                className="rounded-lg border border-violet-200 bg-violet-50/60 px-2.5 py-2 text-xs text-[#5b1fa8] transition hover:bg-violet-100 dark:border-violet-500/30 dark:bg-violet-500/10 dark:text-violet-300"
              >
                {label}
              </button>
            ))}
          </div>
          <p className="mt-4 text-[11px] leading-5 text-muted-foreground">
            点击选项填入要求，补充建议后再提交。成功后直接更新本页；重生成结果卡片可还原。本次会话的还原记录在刷新后失效。
          </p>
        </>
      ) : null}
    </div>
  );
}
