import { MessageSquarePlus, Pencil, Plus, Trash2 } from "lucide-react"
import { useEffect, useState } from "react"

import type { AgentSessionPublic } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

interface SessionBarProps {
  sessions: AgentSessionPublic[]
  currentId: string | null
  busy: boolean
  onSelect: (id: string) => void
  onCreate: () => void
  creating: boolean
  onRename: (id: string, title: string) => void
  renaming: boolean
  onDelete: (id: string) => void
  deleting: boolean
}

const sessionLabel = (s: AgentSessionPublic): string => s.title || "新会话"

/**
 * Shared session switcher strip for agent panels: pick one of the scope's
 * sessions, start a new one (old history stays in the list), rename, delete.
 * Rename/delete use in-app dialogs (the house style, cf. DeleteUser) instead
 * of native prompt/confirm. All actions delegate to the caller's
 * useAgentSessions handlers.
 */
const SessionBar = ({
  sessions,
  currentId,
  busy,
  onSelect,
  onCreate,
  creating,
  onRename,
  renaming,
  onDelete,
  deleting,
}: SessionBarProps) => {
  const current = sessions.find((s) => s.id === currentId) ?? null

  const [renameOpen, setRenameOpen] = useState(false)
  const [titleDraft, setTitleDraft] = useState("")
  const [deleteOpen, setDeleteOpen] = useState(false)

  // prefill the draft whenever the dialog (re)opens for the current session
  useEffect(() => {
    if (renameOpen && current) setTitleDraft(sessionLabel(current))
  }, [renameOpen, current])

  const submitRename = () => {
    if (!current) return
    const title = titleDraft.trim()
    if (title && title !== sessionLabel(current)) onRename(current.id, title)
    setRenameOpen(false)
  }

  return (
    <div className="flex items-center gap-1.5">
      <Select
        value={current?.id ?? ""}
        onValueChange={onSelect}
        disabled={busy || sessions.length === 0}
      >
        <SelectTrigger className="h-8 w-44 text-xs" size="sm">
          <SelectValue
            placeholder={sessions.length ? "选择会话" : "暂无会话"}
          />
        </SelectTrigger>
        <SelectContent>
          {sessions.map((s) => (
            <SelectItem key={s.id} value={s.id} className="text-xs">
              {sessionLabel(s)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button
        size="icon"
        variant="outline"
        className="h-8 w-8"
        title="新建会话（旧会话保留）"
        onClick={onCreate}
        disabled={busy || creating}
      >
        {creating ? (
          <MessageSquarePlus className="h-4 w-4 animate-pulse" />
        ) : (
          <Plus className="h-4 w-4" />
        )}
      </Button>
      {current && (
        <>
          <Button
            size="icon"
            variant="outline"
            className="h-8 w-8"
            title="重命名会话"
            onClick={() => setRenameOpen(true)}
            disabled={busy}
          >
            <Pencil className="h-3.5 w-3.5" />
          </Button>
          <Button
            size="icon"
            variant="outline"
            className="h-8 w-8"
            title="删除会话"
            onClick={() => setDeleteOpen(true)}
            disabled={busy || deleting}
          >
            <Trash2 className="h-4 w-4" />
          </Button>

          {/* Rename dialog */}
          <Dialog open={renameOpen} onOpenChange={setRenameOpen}>
            <DialogContent className="sm:max-w-sm">
              <DialogHeader>
                <DialogTitle>重命名会话</DialogTitle>
                <DialogDescription>
                  修改「{sessionLabel(current)}」的显示名称。
                </DialogDescription>
              </DialogHeader>
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  submitRename()
                }}
              >
                <div className="grid gap-2 py-1">
                  <Label htmlFor="session-title" className="text-sm">
                    会话名称
                  </Label>
                  <Input
                    id="session-title"
                    value={titleDraft}
                    onChange={(e) => setTitleDraft(e.target.value)}
                    autoFocus
                    maxLength={255}
                    disabled={renaming}
                  />
                </div>
                <DialogFooter className="mt-4">
                  <DialogClose asChild>
                    <Button variant="outline" disabled={renaming}>
                      取消
                    </Button>
                  </DialogClose>
                  <LoadingButton
                    type="submit"
                    loading={renaming}
                    disabled={!titleDraft.trim()}
                  >
                    保存
                  </LoadingButton>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>

          {/* Delete confirmation dialog */}
          <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
            <DialogContent className="sm:max-w-md">
              <DialogHeader>
                <DialogTitle>删除会话</DialogTitle>
                <DialogDescription>
                  会话「{sessionLabel(current)}」及其全部历史记录将被
                  <strong>永久删除</strong>
                  ，无法恢复。确定要继续吗？
                </DialogDescription>
              </DialogHeader>
              <DialogFooter className="mt-4">
                <DialogClose asChild>
                  <Button variant="outline" disabled={deleting}>
                    取消
                  </Button>
                </DialogClose>
                <LoadingButton
                  variant="destructive"
                  loading={deleting}
                  onClick={() => {
                    onDelete(current.id)
                    setDeleteOpen(false)
                  }}
                >
                  删除
                </LoadingButton>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </>
      )}
    </div>
  )
}

export default SessionBar
