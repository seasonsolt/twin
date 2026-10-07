import { useRef, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router';
import { Button, Dialog } from '../ui';
import { StageHeader } from './StageHeader';
import { api } from '../../lib/api';
import { useMobile } from '../../lib/useMobile';
import { usePersonas, type Persona } from '../../stores/personas';

export function NewTwin({
  initialOpen = false,
  children = '新建分身',
  className,
  onOpenChange,
}: {
  initialOpen?: boolean;
  children?: ReactNode;
  className?: string;
  onOpenChange?: (open: boolean) => void;
}) {
  const mobile = useMobile();
  const navigate = useNavigate();
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(initialOpen);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const changeOpen = (value: boolean) => {
    setOpen(value);
    onOpenChange?.(value);
  };
  const submit = async () => {
    if (busy || !draft.trim()) return;
    setBusy(true);
    setError('');
    try {
      const created = await api<Persona>('/api/personas', {
        method: 'POST',
        json: { name: draft.trim() },
      });
      await usePersonas.getState().refresh();
      changeOpen(false);
      navigate('/chat');
      await usePersonas.getState().switchTo(created.id);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '创建失败，请重试');
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <button
        ref={trigger}
        type="button"
        aria-label="新建分身"
        aria-haspopup="dialog"
        aria-expanded={open}
        className={
          className ?? 'min-h-11 rounded-full bg-primary px-4 py-2 text-canvas'
        }
        onClick={() => {
          setError('');
          changeOpen(true);
        }}
      >
        {children}
      </button>
      <Dialog
        open={open}
        onOpenChange={changeOpen}
        title="新建分身"
        body="每个分身都有独立的记忆、形象、声音和聊天。"
        className="create-twin-sheet [&_button]:min-h-11 [&_button]:min-w-11"
        style={!mobile ? { translate: 'none' } : undefined}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          trigger.current?.focus();
        }}
      >
        <StageHeader
          variant="future"
          name={draft.trim() || '新分身'}
          intro={<p className="stage-caption">给未来的分身一个名字</p>}
        />
        <div className="space-y-3">
          <Link
            to="/twins"
            className="text-sm text-accent underline"
            onClick={() => changeOpen(false)}
          >
            返回我的分身
          </Link>
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            <label className="block space-y-1">
              分身名字
              <input
                autoFocus
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                maxLength={20}
                required
                className="block min-h-11 w-full rounded-lg border-2 border-primary bg-surface px-3 text-md"
              />
            </label>
            <Button type="submit" loading={busy} disabled={!draft.trim()}>
              创建并开始
            </Button>
          </form>
          {error && (
            <p role="alert" className="text-danger">
              {error}
            </p>
          )}
        </div>
      </Dialog>
    </>
  );
}
