'use client';

import { useState } from 'react';
import { Download, FileUp } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import type { CourseMaterialRecord } from '@/lib/course-space/types';

export function SourceFileEditor({
  courseId,
  material,
  onClose,
  onReplaced,
}: {
  courseId: string;
  material: CourseMaterialRecord;
  onClose: () => void;
  onReplaced: (material: CourseMaterialRecord) => Promise<void>;
}) {
  const [file, setFile] = useState<File>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const url = `/api/course-space/${encodeURIComponent(courseId)}/materials/${encodeURIComponent(material.id)}`;
  const replace = async () => {
    if (!file || busy) return;
    if (!file.size || file.size > 80 * 1024 * 1024) {
      setError('请选择非空文件，且不超过 80MB');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const form = new FormData();
      form.append('file', file);
      const response = await fetch(url, { method: 'PUT', body: form });
      const result = await response.json();
      if (!response.ok || result.success === false) throw new Error(result.error || '替换失败');
      await onReplaced(result.material);
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
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
      <DialogContent className="max-w-lg" showCloseButton={!busy}>
        <DialogHeader>
          <DialogTitle>编辑源文件</DialogTitle>
          <DialogDescription>
            下载“{material.name}
            ”，使用对应软件编辑后，在这里上传替换。新文件保留课时归属和置顶状态，需要重新解析与审核。
          </DialogDescription>
        </DialogHeader>
        <Button variant="outline" asChild>
          <a href={url} download={material.name} target="_blank" rel="noreferrer">
            <Download className="size-4" />
            下载原始文件
          </a>
        </Button>
        <label className="grid gap-3 rounded-xl border border-dashed p-5 text-sm">
          <span className="flex items-center gap-2">
            <FileUp className="size-4" />
            选择编辑后的文件（不超过 80MB）
          </span>
          <input
            type="file"
            aria-label="选择编辑后的文件"
            disabled={busy}
            onChange={(event) => {
              setFile(event.target.files?.[0]);
              setError('');
            }}
            className="min-w-0 text-xs"
          />
        </label>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={onClose}>
            取消
          </Button>
          <Button disabled={!file || busy} onClick={() => void replace()}>
            {busy ? '替换中…' : '替换源文件'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
