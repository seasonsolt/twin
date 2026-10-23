import {
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
  type ReactNode,
} from 'react';
import {
  MoreHorizontal,
  PanelLeftClose,
  Search,
  SquarePen,
} from 'lucide-react';
import {
  Badge,
  Button,
  ChatAction,
  Chip,
  Dialog,
  IconButton,
  Input,
  Row,
  Text,
} from '../../components/ui';
import './history.css';

const groups = ['今天', '更早'] as const;
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

/** One line of the list: a conversation (questions and answers) or a task given to the twin. */
export interface Session {
  kind: 'chat' | 'task';
  id: string;
  title: string;
  updated_at: string;
  /** What was last said, searched together with the title. */
  preview?: string;
  /** A short mark after the title, such as 本人已回. */
  tag?: string;
  /** A task still being worked on: it says so instead of a time, and cannot be deleted yet. */
  running?: boolean;
  /** Whom it is with, named after the title where the list spans people. */
  who?: string;
  /** The twin it belongs to: opening it takes the page there. */
  personaId?: string;
}

/** What a row says under its title, on one line: whom it is with, where what it handed to the person stands, and that
 * it is a task. */
const notes = (row: Session) =>
  [
    row.who,
    row.tag,
    row.kind === 'task' ? (row.running ? '任务 · 在做' : '任务') : '',
  ].filter((note): note is string => !!note);

/** A choice among the people and kinds the list can be narrowed to. */
export interface SessionFilter {
  id: string;
  label: string;
}

/** The person's own assistant, set above the list: its conversations are theirs alone. */
export interface PinnedSessions {
  label: string;
  /** How many wait for the person's decision. */
  waiting?: number;
  selected: boolean;
  onSelect(): void;
}

/**
 * The conversations and tasks with the twin in view, newest first: pick one to go on with it, start a new one,
 * search, and change or delete one from its "⋯". On a wide screen it is the sheet at the left of the page (with
 * ``heading``, the person picker, on top); on a phone it is a dialog.
 */
export function SessionList({
  open,
  onOpenChange,
  sessions,
  current,
  loading = false,
  error = '',
  hasMore = false,
  onMore,
  onRetry,
  onOpen,
  onNew,
  onRename,
  onDelete,
  name,
  inline = false,
  returnFocus,
  now = clock,
  heading,
  presence,
  busy = false,
  newLabel = '新对话',
  filters,
  filter,
  onFilter,
  pinned,
}: {
  open: boolean;
  onOpenChange(open: boolean): void;
  sessions: Session[];
  /** The one open on the page. */
  current: { kind: Session['kind']; id: string } | null;
  loading?: boolean;
  error?: string;
  hasMore?: boolean;
  onMore?(): void;
  onRetry?(): void;
  /** Opening one; false when it could not be opened (the list stays as it is). */
  onOpen(session: Session): Promise<boolean> | boolean;
  onNew(): void;
  /** Only conversations are renamed. */
  onRename?(session: Session, title: string): Promise<void>;
  /** Asks first when it must, then deletes; a rejection is shown in the list. */
  onDelete(session: Session): Promise<void>;
  name: string;
  inline?: boolean;
  returnFocus?: RefObject<HTMLElement | null>;
  now?: () => Date;
  heading?: ReactNode;
  presence?: string;
  /** Opening one is under way: the rows wait. */
  busy?: boolean;
  /** What starting a fresh one is called: 新对话, or 新任务 where the page is on tasks. */
  newLabel?: string;
  /** What the list can be narrowed to (全部, a person, 任务), and the one chosen. */
  filters?: SessionFilter[];
  filter?: string;
  onFilter?(id: string): void;
  pinned?: PinnedSessions;
}) {
  const [menu, setMenu] = useState<string | null>(null);
  const menuTrigger = useRef<HTMLButtonElement | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const [query, setQuery] = useState('');
  const [searchOpen, setSearchOpen] = useState(!inline);
  const [failure, setFailure] = useState('');
  const [saving, setSaving] = useState(false);
  const scroll = useRef<HTMLDivElement>(null);
  const [fade, setFade] = useState(false);
  const currentTime = now();
  const search = query.trim().toLocaleLowerCase();
  const filtered = sessions.filter((row) =>
    `${row.title}\n${row.preview ?? ''}`.toLocaleLowerCase().includes(search),
  );
  const keyOf = (row: Pick<Session, 'kind' | 'id'>) => `${row.kind}:${row.id}`;
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
  }, [open, inline, sessions, loading, query, menu, editing]);
  const reset = () => {
    setMenu(null);
    setEditing(null);
    setFailure('');
  };
  const remove = async (row: Session) => {
    setMenu(null);
    setSaving(true);
    try {
      await onDelete(row);
    } catch (error) {
      setFailure(error instanceof Error ? error.message : '删除失败，请重试');
    } finally {
      setSaving(false);
    }
  };
  const content = (
    <div className="history-content">
      {inline && heading && (
        <Row gap={1}>
          <div className="min-w-0 flex-1">{heading}</div>
          <IconButton label="收起对话列表" onClick={() => onOpenChange(false)}>
            <PanelLeftClose size={18} aria-hidden />
          </IconButton>
        </Row>
      )}
      {inline && presence && (
        <Text size="xs" tone="tertiary" className="px-3">
          {presence}
        </Text>
      )}
      <Row gap={1}>
        <div className="min-w-0 flex-1">
          <ChatAction
            variant="row"
            className="history-new"
            aria-label={newLabel}
            disabled={saving}
            onClick={() => {
              reset();
              setQuery('');
              onNew();
              if (!inline) onOpenChange(false);
            }}
          >
            <SquarePen size={18} aria-hidden /> {newLabel}
          </ChatAction>
        </div>
        {inline && (
          <IconButton
            label="搜索对话"
            aria-expanded={searchOpen}
            onClick={() => setSearchOpen(!searchOpen)}
          >
            <Search size={18} aria-hidden />
          </IconButton>
        )}
        {inline && !heading && (
          <IconButton label="收起对话列表" onClick={() => onOpenChange(false)}>
            <PanelLeftClose size={18} aria-hidden />
          </IconButton>
        )}
      </Row>
      {filters && filters.length > 1 && (
        <div role="group" aria-label="对话范围" className="history-filters">
          {filters.map((option) => (
            <Chip
              key={option.id}
              pressed={option.id === filter}
              onClick={() => onFilter?.(option.id)}
            >
              {option.label}
            </Chip>
          ))}
        </div>
      )}
      {pinned && (
        <Button
          variant="ghost"
          className="history-pinned font-normal"
          aria-pressed={pinned.selected}
          disabled={saving || busy}
          onClick={pinned.onSelect}
        >
          <span className="history-title">{pinned.label}</span>
          {!!pinned.waiting && (
            <Badge tone="warning" title={`${pinned.waiting} 条等你决定`}>
              {pinned.waiting}
            </Badge>
          )}
        </Button>
      )}
      {searchOpen && (
        <Input
          autoFocus={inline}
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
      )}
      {(failure || error) && (
        <p role="alert" className="history-error">
          {failure || error}
        </p>
      )}
      {error && onRetry && (
        <Button variant="ghost" onClick={onRetry}>
          重试加载
        </Button>
      )}
      <div className="history-list-frame" data-fade={fade}>
        <div ref={scroll} className="history-scroll" aria-label="已保存的对话">
          <div>
            {!sessions.length && !loading && !error && (
              <p className="history-empty">还没有对话，问{name}点什么吧</p>
            )}
            {!!sessions.length && !filtered.length && (
              <p className="history-empty">没有找到匹配的对话</p>
            )}
            {groups.map((group) => {
              const rows = filtered.filter(
                (row) =>
                  (dayGroup(row.updated_at, currentTime) === '今天'
                    ? '今天'
                    : '更早') === group,
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
                      {rows.map((row) => {
                        const key = keyOf(row);
                        const isCurrent =
                          current !== null && keyOf(current) === key;
                        return (
                          <li
                            key={key}
                            className="history-entry"
                            data-current={isCurrent}
                          >
                            {editing === key ? (
                              <form
                                className="history-edit"
                                onSubmit={(event) => {
                                  event.preventDefault();
                                  if (!title.trim() || saving || !onRename)
                                    return;
                                  setSaving(true);
                                  setFailure('');
                                  void onRename(row, title.trim())
                                    .then(() => setEditing(null))
                                    .catch((error: unknown) =>
                                      setFailure(
                                        error instanceof Error
                                          ? error.message
                                          : '重命名失败',
                                      ),
                                    )
                                    .finally(() => setSaving(false));
                                }}
                              >
                                <Input
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
                                  <Button
                                    variant="ghost"
                                    className="history-select font-normal text-current hover:bg-transparent"
                                    aria-current={
                                      isCurrent ? 'true' : undefined
                                    }
                                    disabled={saving || busy}
                                    onClick={() => {
                                      setFailure('');
                                      void Promise.resolve(onOpen(row)).then(
                                        (opened) => {
                                          if (opened) {
                                            reset();
                                            if (!inline) onOpenChange(false);
                                          }
                                        },
                                      );
                                    }}
                                  >
                                    <span className="history-title">
                                      {row.title}
                                      {!!notes(row).length && (
                                        <span className="history-kind">
                                          {notes(row).map((note, index) => (
                                            <span key={note}>
                                              {index > 0 && ' · '}
                                              <span>{note}</span>
                                            </span>
                                          ))}
                                        </span>
                                      )}
                                    </span>{' '}
                                    <time dateTime={row.updated_at}>
                                      {row.running
                                        ? '在做'
                                        : relativeTime(
                                            row.updated_at,
                                            currentTime,
                                          )}
                                    </time>
                                  </Button>
                                  <IconButton
                                    className="history-more text-current hover:bg-transparent"
                                    label={`${row.title}的更多操作`}
                                    aria-expanded={menu === key}
                                    aria-haspopup="menu"
                                    disabled={saving || row.running}
                                    onClick={(event) => {
                                      menuTrigger.current = event.currentTarget;
                                      setMenu(menu === key ? null : key);
                                    }}
                                  >
                                    <MoreHorizontal size={18} aria-hidden />
                                  </IconButton>
                                </div>
                                {menu === key && (
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
                                    {onRename && row.kind === 'chat' && (
                                      <Button
                                        autoFocus
                                        variant="ghost"
                                        role="menuitem"
                                        onClick={() => {
                                          setEditing(key);
                                          setTitle(row.title);
                                          setMenu(null);
                                        }}
                                      >
                                        重命名
                                      </Button>
                                    )}
                                    <Button
                                      autoFocus={row.kind === 'task'}
                                      variant="ghost"
                                      role="menuitem"
                                      disabled={saving}
                                      onClick={() => void remove(row)}
                                    >
                                      删除
                                    </Button>
                                  </div>
                                )}
                              </>
                            )}
                          </li>
                        );
                      })}
                    </ul>
                  </section>
                )
              );
            })}
            {loading && (
              <p role="status" className="history-empty">
                正在加载…
              </p>
            )}
            {hasMore && (
              <Button variant="ghost" disabled={loading} onClick={onMore}>
                显示更多
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
  if (inline)
    return (
      <section
        className="conversation-sheet-history"
        aria-label={`和${name}的对话`}
      >
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
