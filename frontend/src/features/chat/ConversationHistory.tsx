import { useLayoutEffect, useRef, useState, type RefObject } from 'react';
import { MoreHorizontal } from 'lucide-react';
import { Button, Dialog, useConfirm } from '../../components/ui';
import type { useConversation, ConversationSummary } from './useConversation';
import './history.css';

const groups = ['今天', '昨天', '更早'] as const;
const clock = () => new Date();

export function dayGroup(timestamp: string, now: Date) {
  const date = new Date(timestamp);
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === now.toDateString()) return '今天';
  if (date.toDateString() === yesterday.toDateString()) return '昨天';
  return '更早';
}

export function relativeTime(timestamp: string, now: Date) {
  const date = new Date(timestamp);
  const group = dayGroup(timestamp, now);
  if (group === '今天')
    return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
  if (group === '昨天') return '昨天';
  return `${date.getMonth() + 1}月${date.getDate()}日`;
}

export function ConversationHistory({
  open,
  onOpenChange,
  chat,
  onResume,
  onNew,
  name,
  inline = false,
  returnFocus,
  now = clock,
}: {
  open: boolean;
  onOpenChange(open: boolean): void;
  chat: ReturnType<typeof useConversation>;
  onResume(): void;
  onNew(): void;
  name: string;
  inline?: boolean;
  returnFocus?: RefObject<HTMLElement | null>;
  now?: () => Date;
}) {
  const confirm = useConfirm();
  const [menu, setMenu] = useState<string | null>(null);
  const menuTrigger = useRef<HTMLButtonElement | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const scroll = useRef<HTMLDivElement>(null);
  const [fade, setFade] = useState(false);
  const currentTime = now();
  const search = query.trim().toLocaleLowerCase();
  const filtered = chat.history.filter((row) =>
    `${row.title}\n${row.preview}`.toLocaleLowerCase().includes(search),
  );
  useLayoutEffect(() => {
    const list = scroll.current;
    if (!list) return;
    const update = () =>
      setFade(list.scrollHeight - list.clientHeight - list.scrollTop > 1);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(list);
    if (list.firstElementChild) observer.observe(list.firstElementChild);
    list.addEventListener('scroll', update, { passive: true });
    return () => {
      observer.disconnect();
      list.removeEventListener('scroll', update);
    };
  }, [open, inline, chat.history, chat.historyLoading, query, menu, editing]);
  const reset = () => {
    setMenu(null);
    setEditing(null);
    setError('');
  };
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
  const content = (
    <div className="history-content">
      <button
        type="button"
        className="history-new"
        aria-label="新对话"
        disabled={saving}
        onClick={() => {
          reset();
          setQuery('');
          onNew();
          onOpenChange(false);
        }}
      >
        ＋ 新对话
      </button>
      <input
        type="search"
        aria-label="搜索对话"
        placeholder="搜索对话"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setMenu(null);
          if (scroll.current) scroll.current.scrollTop = 0;
        }}
        className="history-search"
      />
      {(error || chat.historyError) && (
        <p role="alert" className="history-error">
          {error || chat.historyError}
        </p>
      )}
      {chat.historyError && (
        <Button variant="ghost" onClick={() => void chat.refreshHistory()}>
          重试加载
        </Button>
      )}
      <div className="history-list-frame" data-fade={fade}>
        <div ref={scroll} className="history-scroll" aria-label="已保存的对话">
          <div>
            {!chat.history.length &&
              !chat.historyLoading &&
              !chat.historyError && (
                <p className="history-empty">还没有对话，问他点什么吧</p>
              )}
            {!!chat.history.length && !filtered.length && (
              <p className="history-empty">没有找到匹配的对话</p>
            )}
            {groups.map((group) => {
              const rows = filtered.filter(
                (row) => dayGroup(row.updated_at, currentTime) === group,
              );
              return (
                rows.length > 0 && (
                  <section
                    key={group}
                    className="history-group"
                    aria-label={group}
                  >
                    <h3 className="history-group-label">{group}</h3>
                    <ul className="history-list">
                      {rows.map((row) => (
                        <li
                          key={row.id}
                          className="history-entry"
                          data-current={row.id === chat.conversationId}
                        >
                          {editing === row.id ? (
                            <form
                              className="history-edit"
                              onSubmit={(event) => {
                                event.preventDefault();
                                if (!title.trim() || saving) return;
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
                                onChange={(event) =>
                                  setTitle(event.target.value)
                                }
                                className="history-search"
                              />
                              <div className="mt-2 flex justify-end gap-2">
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  disabled={saving}
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
                              <div className="history-entry-row">
                                <button
                                  type="button"
                                  className="history-select"
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
                                        reset();
                                        onResume();
                                        onOpenChange(false);
                                      }
                                    });
                                  }}
                                >
                                  <span className="history-title">
                                    {row.title}
                                  </span>{' '}
                                  <time dateTime={row.updated_at}>
                                    {relativeTime(row.updated_at, currentTime)}
                                  </time>
                                </button>
                                <button
                                  type="button"
                                  className="history-more"
                                  aria-label={`${row.title}的更多操作`}
                                  aria-expanded={menu === row.id}
                                  aria-haspopup="menu"
                                  disabled={saving}
                                  onClick={(event) => {
                                    menuTrigger.current = event.currentTarget;
                                    setMenu(menu === row.id ? null : row.id);
                                  }}
                                >
                                  <MoreHorizontal size={18} aria-hidden />
                                </button>
                              </div>
                              {menu === row.id && (
                                <div
                                  role="menu"
                                  aria-label="对话操作"
                                  className="history-menu"
                                  onKeyDown={(event) => {
                                    if (event.key === 'Escape') {
                                      event.preventDefault();
                                      event.stopPropagation();
                                      setMenu(null);
                                      menuTrigger.current?.focus();
                                    } else if (
                                      [
                                        'ArrowDown',
                                        'ArrowUp',
                                        'Home',
                                        'End',
                                      ].includes(event.key)
                                    ) {
                                      event.preventDefault();
                                      const items = Array.from(
                                        event.currentTarget.querySelectorAll<HTMLButtonElement>(
                                          '[role="menuitem"]',
                                        ),
                                      );
                                      const index = items.indexOf(
                                        document.activeElement as HTMLButtonElement,
                                      );
                                      const next =
                                        event.key === 'Home'
                                          ? 0
                                          : event.key === 'End'
                                            ? items.length - 1
                                            : (index +
                                                (event.key === 'ArrowDown'
                                                  ? 1
                                                  : -1) +
                                                items.length) %
                                              items.length;
                                      items[next]?.focus();
                                    }
                                  }}
                                >
                                  <button
                                    autoFocus
                                    type="button"
                                    role="menuitem"
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
            {chat.historyLoading && (
              <p role="status" className="history-empty">
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
          </div>
        </div>
      </div>
    </div>
  );
  if (inline)
    return (
      <section className="stage-history" aria-label={`和${name}的对话`}>
        <h2 className="history-heading">和{name}的对话</h2>
        {content}
      </section>
    );
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        reset();
        onOpenChange(value);
      }}
      title="对话记录"
      onEscapeKeyDown={(event) => {
        if (menu) {
          event.preventDefault();
          setMenu(null);
          menuTrigger.current?.focus();
        }
      }}
      onCloseAutoFocus={(event) => {
        if (returnFocus?.current?.isConnected) {
          event.preventDefault();
          returnFocus.current.focus();
        }
      }}
      className="conversation-history history-sheet"
    >
      {content}
    </Dialog>
  );
}
