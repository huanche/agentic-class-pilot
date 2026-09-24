'use client';

import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, FileCheck2, ShieldCheck, XCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import type { Scene } from '@/lib/types/stage';
import type { CourseGovernanceRecord, CourseReleaseGateResult, SceneReviewState } from '@/lib/course-governance/contracts';
import {
  evaluateCourseReleaseGate,
  loadCourseGovernance,
  setSceneReview,
} from '@/lib/course-governance/governance';

interface CourseReleaseReviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  stageId?: string;
  scenes: Scene[];
  onChanged?: () => void;
}

export function CourseReleaseReviewDialog({
  open,
  onOpenChange,
  stageId,
  scenes,
  onChanged,
}: CourseReleaseReviewDialogProps) {
  const [record, setRecord] = useState<CourseGovernanceRecord>();
  const [gate, setGate] = useState<CourseReleaseGateResult>();
  const [selectedOrder, setSelectedOrder] = useState<number>();
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);

  const sortedScenes = useMemo(() => [...scenes].sort((a, b) => a.order - b.order), [scenes]);
  const selectedScene = sortedScenes.find((scene) => scene.order === selectedOrder) || sortedScenes[0];
  const selectedReview = record?.sceneReviews.find((item) => item.sceneOrder === selectedScene?.order);
  const selectedDegradations = record?.degradations.filter(
    (item) => item.sceneOrder === selectedScene?.order,
  ) || [];

  const refresh = async () => {
    if (!stageId) return;
    const nextRecord = await loadCourseGovernance(stageId);
    setRecord(nextRecord);
    setGate(await evaluateCourseReleaseGate(stageId, scenes));
    if (selectedOrder === undefined && sortedScenes[0]) setSelectedOrder(sortedScenes[0].order);
  };

  useEffect(() => {
    if (open) void refresh();
  }, [open, stageId, scenes.length]);

  useEffect(() => {
    setNote(selectedReview?.reviewerNote || '');
  }, [selectedReview?.sceneOrder, selectedReview?.reviewerNote]);

  const updateReview = async (state: SceneReviewState) => {
    if (!stageId || !selectedScene) return;
    setSaving(true);
    try {
      const updated = await setSceneReview({
        stageId,
        scene: selectedScene,
        state,
        reviewerNote: note,
      });
      setRecord(updated);
      setGate(await evaluateCourseReleaseGate(stageId, scenes));
      onChanged?.();
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[88vh] overflow-hidden sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ShieldCheck className="size-5 text-emerald-600" />课程来源与发布审核
          </DialogTitle>
          <DialogDescription>
            每个场景都必须有来源引用并单独审核。审核后修改场景会使批准自动失效。
          </DialogDescription>
        </DialogHeader>

        {!record ? (
          <div className="rounded-xl border p-6 text-sm text-muted-foreground">
            当前课堂不是从受治理的 PPT/PDF 转换流程创建，无需执行本发布门禁。
          </div>
        ) : (
          <div className="grid min-h-0 gap-4 lg:grid-cols-[280px_1fr]">
            <div className="min-h-0 space-y-3 overflow-y-auto rounded-xl border p-3">
              <div className="rounded-lg bg-muted p-3 text-xs leading-relaxed">
                <div className="font-medium">{record.source.fileName}</div>
                <div>{record.source.pageCount} 页 · {record.source.byteLength.toLocaleString()} bytes</div>
                <div className="mt-1 break-all font-mono text-[10px] text-muted-foreground">
                  SHA-256 {record.source.sha256}
                </div>
              </div>
              {record.sceneReviews.map((review) => {
                const Icon = review.state === 'approved' ? CheckCircle2 : review.state === 'rejected' ? XCircle : AlertTriangle;
                return (
                  <button
                    key={review.sceneOrder}
                    type="button"
                    onClick={() => setSelectedOrder(review.sceneOrder)}
                    className={`flex w-full items-start gap-2 rounded-lg border p-3 text-left text-sm transition ${selectedScene?.order === review.sceneOrder ? 'border-blue-400 bg-blue-50 dark:bg-blue-950/30' : 'hover:bg-muted'}`}
                  >
                    <Icon className={`mt-0.5 size-4 shrink-0 ${review.state === 'approved' ? 'text-emerald-600' : review.state === 'rejected' ? 'text-red-600' : 'text-amber-500'}`} />
                    <span className="min-w-0">
                      <span className="block truncate">{review.sceneOrder}. {review.title}</span>
                      <span className="text-xs text-muted-foreground">来源 {review.sourceRefs.length} 条 · {review.state}</span>
                    </span>
                  </button>
                );
              })}
            </div>

            <div className="min-h-0 space-y-4 overflow-y-auto rounded-xl border p-5">
              {selectedScene && selectedReview && (
                <>
                  <div>
                    <div className="text-xs uppercase tracking-widest text-muted-foreground">场景 {selectedScene.order}</div>
                    <h3 className="mt-1 text-lg font-semibold">{selectedScene.title}</h3>
                  </div>

                  <section>
                    <h4 className="mb-2 flex items-center gap-2 text-sm font-medium"><FileCheck2 className="size-4" />来源引用</h4>
                    <div className="space-y-2">
                      {selectedReview.sourceRefs.map((ref) => (
                        <div key={`${ref.slideNumber}-${ref.sourceSlideId || ''}`} className="rounded-lg bg-muted/60 p-3 text-xs">
                          <div className="font-medium">原材料第 {ref.slideNumber} 页{ref.title ? ` · ${ref.title}` : ''}</div>
                          {ref.excerpt && <p className="mt-1 line-clamp-3 text-muted-foreground">{ref.excerpt}</p>}
                        </div>
                      ))}
                    </div>
                  </section>

                  {selectedDegradations.length > 0 && (
                    <section>
                      <h4 className="mb-2 text-sm font-medium">自动降级记录</h4>
                      <div className="space-y-2">
                        {selectedDegradations.map((item) => (
                          <div key={item.id} className={`rounded-lg border p-3 text-xs ${item.status === 'unresolved' ? 'border-red-300 bg-red-50 dark:bg-red-950/20' : 'border-amber-200 bg-amber-50 dark:bg-amber-950/20'}`}>
                            <div className="font-medium">{item.kind} · {item.status}</div>
                            <div className="mt-1 text-muted-foreground">{item.reason}</div>
                            <div className="mt-1">回退：{item.fallback}</div>
                          </div>
                        ))}
                      </div>
                    </section>
                  )}

                  <label className="block space-y-2 text-sm font-medium">
                    审核意见
                    <Textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="记录公式、关键数值、讲解、互动和降级项的核验结果" />
                  </label>

                  <div className="flex flex-wrap gap-3">
                    <Button onClick={() => updateReview('approved')} disabled={saving}>
                      <CheckCircle2 className="mr-2 size-4" />批准当前场景
                    </Button>
                    <Button variant="destructive" onClick={() => updateReview('rejected')} disabled={saving}>
                      <XCircle className="mr-2 size-4" />退回修改
                    </Button>
                  </div>
                </>
              )}

              {gate && (
                <div className={`rounded-xl border p-4 text-sm ${gate.ready ? 'border-emerald-300 bg-emerald-50 dark:bg-emerald-950/20' : 'border-amber-300 bg-amber-50 dark:bg-amber-950/20'}`}>
                  <div className="font-semibold">{gate.ready ? '发布门禁已通过' : '发布门禁尚未通过'}</div>
                  <div className="mt-1">已批准 {gate.approvedScenes} / {gate.totalScenes} 个场景</div>
                  {!gate.ready && <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-muted-foreground">{gate.reasons.slice(0, 6).map((reason) => <li key={reason}>{reason}</li>)}</ul>}
                </div>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
