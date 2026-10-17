'use client';

import { useRef, type ReactNode } from 'react';
import { MoreHorizontal, Pin } from 'lucide-react';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu';
import {
  ContextMenu,
  ContextMenuTrigger,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
} from '@/components/ui/context-menu';

export interface WorkspaceMenuAction {
  label: string;
  icon: ReactNode;
  onSelect: () => void;
  disabled?: boolean;
  destructive?: boolean;
  separator?: boolean;
  movesFocus?: boolean;
}

export function WorkspaceItemMenu({
  title,
  pinned,
  children,
  actions,
}: {
  title: string;
  pinned?: boolean;
  children?: ReactNode;
  actions: WorkspaceMenuAction[];
}) {
  const focusAction = useRef<(() => void) | undefined>(undefined);
  const restoreFocus = (event: Event) => {
    const action = focusAction.current;
    if (!action) return;
    event.preventDefault();
    focusAction.current = undefined;
    // Wait until the menu's focus scope closes before selecting an editor or
    // revealing a row; its exit animation otherwise traps the new focus.
    action();
  };
  const menu = (context: boolean) => {
    const Item = context ? ContextMenuItem : DropdownMenuItem;
    const Separator = context ? ContextMenuSeparator : DropdownMenuSeparator;
    return actions.map((action) => (
      <div key={action.label}>
        {action.separator && <Separator />}
        <Item
          disabled={action.disabled}
          onSelect={() => {
            if (action.movesFocus) focusAction.current = action.onSelect;
            else action.onSelect();
          }}
          className={action.destructive ? 'text-destructive focus:text-destructive' : undefined}
        >
          {action.icon}
          {action.label}
        </Item>
      </div>
    ));
  };
  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>
        <div className="group/item flex min-w-0 flex-1 items-center rounded-lg hover:bg-slate-100 focus-within:bg-slate-100">
          {children && <div className="min-w-0 flex-1">{children}</div>}
          {children && pinned && (
            <Pin aria-label="已置顶" className="size-3 shrink-0 text-[#B00055]" />
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label={`管理“${title}”`}
                title={`管理“${title}”`}
                className="mx-0.5 grid size-7 shrink-0 place-items-center rounded-md text-slate-500 hover:bg-slate-200 focus-visible:outline-2 focus-visible:outline-[#B00055]"
              >
                <MoreHorizontal className="size-4" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-48" onCloseAutoFocus={restoreFocus}>
              {menu(false)}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </ContextMenuTrigger>
      <ContextMenuContent className="w-48" onCloseAutoFocus={restoreFocus}>
        {menu(true)}
      </ContextMenuContent>
    </ContextMenu>
  );
}
