'use client';

import { useState } from 'react';
import { ArrowLeft, Settings } from 'lucide-react';

import { SettingsDialog } from '@/components/settings';
import { Button } from '@/components/ui/button';
import { platformHomeUrl } from '@/lib/integration/platform-links';

export default function ModelSettingsPage() {
  const [open, setOpen] = useState(true);

  return (
    <main className="min-h-screen bg-gradient-to-br from-rose-50 via-white to-slate-50 p-6">
      <div className="mx-auto flex max-w-5xl items-center justify-between rounded-2xl border bg-white/90 p-5 shadow-sm">
        <div>
          <p className="text-sm font-medium text-[#B00055]">AI 教育平台 · 教师端</p>
          <h1 className="mt-1 text-2xl font-semibold text-slate-900">模型与能力配置</h1>
          <p className="mt-2 text-sm text-slate-500">
            配置语言模型、图像、语音、文档解析和联网搜索能力。
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => window.location.assign(platformHomeUrl())}>
            <ArrowLeft className="mr-2 size-4" />返回平台
          </Button>
          <Button onClick={() => setOpen(true)}>
            <Settings className="mr-2 size-4" />打开配置
          </Button>
        </div>
      </div>

      <SettingsDialog open={open} onOpenChange={setOpen} initialSection="providers" />
    </main>
  );
}
