import { useState } from 'react';
import { MoreHorizontal } from 'lucide-react';
import { Button, Dialog, useConfirm } from '../../components/ui';
import { useMobile } from '../../lib/useMobile';
import type { useConversation, ConversationSummary } from './useConversation';
import './history.css';

function dayGroup(timestamp: string) {
  const date = new Date(timestamp);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return '今天';
  if (date.toDateString() === yesterday.toDateString()) return '昨天';
  return '更早';
}
export function ConversationHistory({
  open,
  onOpenChange,
  chat,
  onResume,
}: {
  open: boolean;
  onOpenChange(open: boolean): void;
  chat: ReturnType<typeof useConversation>;
  onResume(): void;
}) {
  const mobile = useMobile();
  const confirm = useConfirm();
  const [menu, setMenu] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const remove = async (row: ConversationSummary) => {
    setMenu(null);
    if (
      !(await confirm({
        title: '删除对话？',
        body: `“${row.title}”将被永久删除。`,
        confirmLabel: '删除',
        tone: 'danger',
      }))
    )
      return;
    setSaving(true);
    try {
      await chat.remove(row.id);
      if (row.id === chat.conversationId) onResume();
    } catch (error) {
      setError(error instanceof Error ? error.message : '删除失败，请重试');
    } finally {
      setSaving(false);
    }
  };
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        setMenu(null);
        setEditing(null);
        setError('');
        onOpenChange(value);
      }}
      title="对话记录"
      body="找到以前的对话，接着聊。"
      popover={!mobile}
      className={`conversation-history ${mobile ? 'history-sheet' : 'history-panel'}`}
    >
      {(error || chat.historyError) && (
        <p role="alert" className="mb-3 text-sm text-danger">
          {error || chat.historyError}
        </p>
      )}
      {chat.historyError && (
        <Button variant="ghost" onClick={() => void chat.refreshHistory()}>
          重试加载
        </Button>
      )}
      {!chat.history.length && !chat.historyLoading && !chat.historyError && (
        <p className="py-10 text-center text-secondary">还没有对话记录</p>
      )}
      <div aria-label="已保存的对话">
        {(['今天', '昨天', '更早'] as const).map((group) => {
          const rows = chat.history.filter(
            (row) => dayGroup(row.updated_at) === group,
          );
          return (
            rows.length > 0 && (
              <section key={group} className="mb-5">
                <h3 className="mb-2 text-xs text-secondary">{group}</h3>
                <ul className="space-y-2">
                  {rows.map((row) => (
                    <li
                      key={row.id}
                      className="history-entry"
                      data-current={row.id === chat.conversationId}
                    >
                      {editing === row.id ? (
                        <form
                          className="p-3"
                          onSubmit={(event) => {
                            event.preventDefault();
                            setSaving(true);
                            setError('');
                            void chat
                              .rename(row.id, title.trim())
                              .then(() => setEditing(null))
                              .catch((error: unknown) =>
                                setError(
                                  error instanceof Error
                                    ? error.message
                                    : '重命名失败',
                                ),
                              )
                              .finally(() => setSaving(false));
                          }}
                        >
                          <input
                            autoFocus
                            aria-label="对话标题"
                            maxLength={200}
                            value={title}
                            onChange={(event) => setTitle(event.target.value)}
                            className="min-h-11 w-full rounded-md border border-border bg-canvas px-2"
                          />
                          <div className="mt-2 flex justify-end gap-2">
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => setEditing(null)}
                            >
                              取消
                            </Button>
                            <Button
                              size="sm"
                              type="submit"
                              disabled={!title.trim() || saving}
                            >
                              保存
                            </Button>
                          </div>
                        </form>
                      ) : (
                        <>
                          <div className="flex items-start">
                            <button
                              type="button"
                              className="min-w-0 flex-1 p-3 text-left"
                              aria-current={
                                row.id === chat.conversationId
                                  ? 'true'
                                  : undefined
                              }
                              disabled={saving || chat.loading}
                              onClick={() => {
                                setError('');
                                void chat.resume(row.id).then((loaded) => {
                                  if (loaded) {
                                    onResume();
                                    onOpenChange(false);
                                  }
                                });
                              }}
                            >
                              <span className="block truncate font-medium">
                                {row.title}
                              </span>
                              <time
                                dateTime={row.updated_at}
                                className="block text-xs text-secondary"
                              >
                                {new Date(row.updated_at).toLocaleString(
                                  'zh-CN',
                                  {
                                    month: 'numeric',
                                    day: 'numeric',
                                    hour: '2-digit',
                                    minute: '2-digit',
                                  },
                                )}
                              </time>
                              <span className="mt-1 block truncate text-sm text-secondary">
                                {row.preview || '还没有消息'}
                              </span>
                            </button>
                            <button
                              type="button"
                              className="min-h-11 min-w-11"
                              aria-label={`${row.title}的更多操作`}
                              aria-expanded={menu === row.id}
                              aria-haspopup="menu"
                              onClick={() =>
                                setMenu(menu === row.id ? null : row.id)
                              }
                            >
                              <MoreHorizontal size={18} aria-hidden />
                            </button>
                          </div>
                          {menu === row.id && (
                            <div
                              role="menu"
                              aria-label="对话操作"
                              className="flex justify-end gap-2 px-3 pb-2"
                            >
                              <button
                                type="button"
                                role="menuitem"
                                className="min-h-11 px-2"
                                onClick={() => {
                                  setEditing(row.id);
                                  setTitle(row.title);
                                  setMenu(null);
                                }}
                              >
                                重命名
                              </button>
                              <button
                                type="button"
                                role="menuitem"
                                className="min-h-11 px-2 text-danger"
                                disabled={saving}
                                onClick={() => void remove(row)}
                              >
                                删除
                              </button>
                            </div>
                          )}
                        </>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            )
          );
        })}
      </div>
      {chat.historyLoading && (
        <p role="status" className="py-3 text-center text-secondary">
          正在加载…
        </p>
      )}
      {chat.hasMore && (
        <Button
          variant="ghost"
          disabled={chat.historyLoading}
          onClick={() => void chat.refreshHistory(chat.history.length)}
        >
          更多对话
        </Button>
      )}
    </Dialog>
  );
}
