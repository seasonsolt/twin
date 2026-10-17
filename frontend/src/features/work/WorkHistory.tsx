import { useState, type RefObject } from 'react';
import { Trash2 } from 'lucide-react';
import { Button, Dialog, IconButton, Input } from '../../components/ui';
import { dayGroup, relativeTime } from '../chat/ConversationHistory';
import '../chat/history.css';
import type { WorkSummary } from './types';

const groups = ['今天', '昨天', '更早'] as const;
const clock = () => new Date();

/** The tasks list of work mode, laid out like chat's conversation history: inline in the stage on a wide
 * screen, a sheet on a phone. */
export function WorkHistory({
  tasks,
  error,
  current,
  open,
  onOpenChange,
  onOpen,
  onNew,
  onDelete,
  onRetry,
  name,
  inline = false,
  returnFocus,
  now = clock,
}: {
  tasks: WorkSummary[] | null;
  error: string;
  current: string | null;
  open: boolean;
  onOpenChange(open: boolean): void;
  onOpen(taskId: string): void;
  onNew(): void;
  onDelete(task: WorkSummary): void;
  onRetry(): void;
  name: string;
  inline?: boolean;
  returnFocus?: RefObject<HTMLElement | null>;
  now?: () => Date;
}) {
  const [query, setQuery] = useState('');
  const currentTime = now();
  const search = query.trim().toLocaleLowerCase();
  const filtered = (tasks ?? []).filter((task) =>
    task.title.toLocaleLowerCase().includes(search),
  );
  const content = (
    <div className="history-content">
      <Button
        variant="ghost"
        className="history-new"
        aria-label="新任务"
        onClick={() => {
          setQuery('');
          onNew();
          onOpenChange(false);
        }}
      >
        ＋ 新任务
      </Button>
      <Input
        type="search"
        aria-label="搜索任务"
        placeholder="搜索任务"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        className="history-search"
      />
      {error && (
        <>
          <p role="alert" className="history-error">
            {error}
          </p>
          <Button variant="ghost" onClick={onRetry}>
            重试加载
          </Button>
        </>
      )}
      <div className="history-list-frame">
        <div className="history-scroll" aria-label="任务">
          <div>
            {tasks === null && !error && (
              <p role="status" className="history-empty">
                正在加载…
              </p>
            )}
            {tasks?.length === 0 && (
              <p className="history-empty">还没有任务，交代一件事吧</p>
            )}
            {!!tasks?.length && !filtered.length && (
              <p className="history-empty">没有找到匹配的任务</p>
            )}
            {groups.map((group) => {
              const rows = filtered.filter(
                (task) => dayGroup(task.updated_at, currentTime) === group,
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
                      {rows.map((task) => (
                        <li
                          key={task.task_id}
                          className="history-entry"
                          data-current={task.task_id === current}
                        >
                          <div className="history-entry-row">
                            <Button
                              variant="ghost"
                              className="history-select font-normal text-current hover:bg-transparent"
                              aria-current={
                                task.task_id === current ? 'true' : undefined
                              }
                              onClick={() => {
                                onOpen(task.task_id);
                                onOpenChange(false);
                              }}
                            >
                              <span className="history-title">
                                {task.title}
                              </span>{' '}
                              <time dateTime={task.updated_at}>
                                {task.status === 'running'
                                  ? '在做'
                                  : relativeTime(task.updated_at, currentTime)}
                              </time>
                            </Button>
                            <IconButton
                              className="history-more text-current hover:bg-transparent"
                              label={`删除${task.title}`}
                              disabled={task.status === 'running'}
                              onClick={() => onDelete(task)}
                            >
                              <Trash2 size={16} aria-hidden />
                            </IconButton>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </section>
                )
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
  if (inline)
    return (
      <section className="stage-history" aria-label={`交给${name}的事`}>
        <h2 className="history-heading">交给{name}的事</h2>
        {content}
      </section>
    );
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="任务记录"
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
