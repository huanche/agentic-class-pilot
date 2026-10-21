'use client';

import { useEffect, useState } from 'react';
import dynamic from 'next/dynamic';
import { Settings } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useSettingsStore } from '@/lib/store/settings';
import { useTheme } from '@/lib/hooks/use-theme';
import { useI18n } from '@/lib/hooks/use-i18n';
import { supportedLocales } from '@/lib/i18n';

const SettingsDialog = dynamic(
  () => import('@/components/settings').then((m) => m.SettingsDialog),
  { ssr: false },
);
const SETTINGS_CHANGED = 'teacher-workspace-settings-changed';

/** Available before any classroom exists, without leaving the current course. */
export function WorkspaceSettingsButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className="gap-1.5 rounded-full"
        onClick={() => setOpen(true)}
      >
        <Settings className="size-4" />
        设置
      </Button>
      {open && (
        <SettingsDialog
          open={open}
          initialSection="general"
          onOpenChange={(next) => {
            setOpen(next);
            if (!next)
              document
                .querySelectorAll<HTMLIFrameElement>('iframe[data-courseware-preview]')
                .forEach((frame) => {
                  frame.contentWindow?.postMessage(
                    { type: SETTINGS_CHANGED },
                    window.location.origin,
                  );
                });
          }}
        />
      )}
    </>
  );
}

/** The preview has its own window/store; adopt settings without reloading its edits. */
export function EmbeddedSettingsSync() {
  const { setTheme } = useTheme();
  const { setLocale } = useI18n();
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (
        event.origin !== window.location.origin ||
        event.source !== window.parent ||
        event.data?.type !== SETTINGS_CHANGED
      )
        return;
      void useSettingsStore.persist.rehydrate();
      try {
        const theme = localStorage.getItem('theme');
        if (theme === 'light' || theme === 'dark' || theme === 'system') setTheme(theme);
        const locale = supportedLocales.find(
          (item) => item.code === localStorage.getItem('locale'),
        );
        if (locale) setLocale(locale.code);
      } catch {
        /* provider rehydration still works when local storage is unavailable */
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [setTheme, setLocale]);
  return null;
}
