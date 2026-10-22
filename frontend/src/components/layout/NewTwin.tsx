import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router';
import { create } from 'zustand';
import {
  Button,
  Card,
  Dialog,
  Field,
  Heading,
  Input,
  Row,
  Stack,
  Text,
} from '../ui';
import { useMobile } from '../../lib/useMobile';
import { api } from '../../lib/api';
import { usePersonas, type Persona } from '../../stores/personas';
import { useAuth } from '../../stores/auth';

// Someone's first twin is most likely of themselves: start from the name their company account gives.
const accountName = () =>
  Array.from(useAuth.getState().identity?.name ?? '')
    .slice(0, 20)
    .join('');

/** The new-twin card opened from somewhere without a trigger of its own (the twin switcher's link). */
export const useNewTwinCard = create<{
  open: boolean;
  set: (open: boolean) => void;
}>((set) => ({ open: false, set: (open) => set({ open }) }));

/**
 * The name of a new twin, its first character shown as it is typed, and 创建并开始, which makes it, switches to it
 * and opens its chat. Used on the page itself where there is nothing else to look at, and in a small card otherwise.
 */
export function NewTwinForm({
  prefill,
  onCreated,
  onCancel,
}: {
  /** Start from the account's name; by default only while the signed-in person has no twin of their own. */
  prefill?: boolean;
  /** Called once the twin exists, before its chat opens. */
  onCreated?: () => void;
  /** Shows 取消, for a form that took the place of something. */
  onCancel?: () => void;
}) {
  const navigate = useNavigate();
  const [draft, setDraft] = useState(() =>
    (prefill ?? !usePersonas.getState().items.some((item) => item.mine))
      ? accountName()
      : '',
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const nameId = useId();
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
      onCreated?.();
      navigate('/chat');
      await usePersonas.getState().switchTo(created.id);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '创建失败，请重试');
    } finally {
      setBusy(false);
    }
  };
  return (
    <Stack gap={4}>
      <Stack
        as="form"
        gap={3}
        aria-label="新建分身"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <Field id={nameId} label="分身名字">
          <Row gap={3}>
            <span aria-hidden className="new-twin-initial">
              {Array.from(draft.trim() || '新')[0]}
            </span>
            <Row grow>
              <Input
                id={nameId}
                autoFocus
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                maxLength={20}
                placeholder="比如你的名字"
                required
                size="lg"
              />
            </Row>
          </Row>
        </Field>
        <Button
          type="submit"
          size="lg"
          className="min-h-12 w-full"
          loading={busy}
          disabled={!draft.trim()}
        >
          创建并开始
        </Button>
        {onCancel && (
          <Button variant="ghost" disabled={busy} onClick={onCancel}>
            取消
          </Button>
        )}
        {error && (
          <Text role="alert" size="sm" tone="danger">
            {error}
          </Text>
        )}
      </Stack>
      <Text size="sm" tone="secondary">
        下一步：加一段会议录音，勾出哪位是你。
      </Text>
    </Stack>
  );
}

export function NewTwin({
  initialOpen = false,
  children = '新建分身',
  variant = 'button',
  onOpenChange,
}: {
  initialOpen?: boolean;
  /** The trigger's content. */
  children?: ReactNode;
  /**
   * button: a primary button, opening a small card over the work in view. card: the dashed tile in the twins grid,
   * which turns into the form in place (nothing there to keep in view).
   */
  variant?: 'button' | 'card';
  onOpenChange?: (open: boolean) => void;
}) {
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(initialOpen);
  const mobile = useMobile();
  const returnFocus = useRef(false);
  const headingId = useId();
  // The tile comes back after 取消: focus goes back to it.
  useEffect(() => {
    if (!open && returnFocus.current) {
      returnFocus.current = false;
      trigger.current?.focus();
    }
  }, [open]);
  const changeOpen = (value: boolean) => {
    setOpen(value);
    onOpenChange?.(value);
  };
  const triggerProps = {
    ref: trigger,
    'aria-expanded': open,
    onClick: () => changeOpen(true),
  };
  if (variant === 'card')
    return open ? (
      <Card as="section" padding="lg" aria-labelledby={headingId}>
        <Stack gap={4}>
          <Heading id={headingId} level={2} size="title">
            新建分身
          </Heading>
          <NewTwinForm
            onCreated={() => changeOpen(false)}
            onCancel={() => {
              returnFocus.current = true;
              changeOpen(false);
            }}
          />
        </Stack>
      </Card>
    ) : (
      <Card
        as="div"
        variant="outline"
        padding="none"
        className="twin-card twin-card-create overflow-hidden border-2 border-dashed border-primary bg-transparent"
      >
        <Button
          {...triggerProps}
          variant="ghost"
          aria-label="新建分身"
          className="h-full min-h-60 w-full flex-col gap-4 p-6 text-primary hover:bg-transparent"
        >
          {children}
        </Button>
      </Card>
    );
  return (
    <>
      <Button
        {...triggerProps}
        aria-haspopup="dialog"
        size="lg"
        aria-label="新建分身"
      >
        {children}
      </Button>
      {/* Over work in view: a card in the middle of the page, from the bottom edge on a phone. The page behind is only
          dimmed and is there again when it closes. */}
      <Dialog
        open={open}
        onOpenChange={changeOpen}
        title="新建分身"
        variant={mobile ? 'sheet' : 'center'}
        className="new-twin"
        inPlace
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          trigger.current?.focus();
        }}
      >
        <NewTwinForm onCreated={() => changeOpen(false)} />
      </Dialog>
    </>
  );
}

/** The new-twin card for `useNewTwinCard`: over the page in view, which is there again when it closes. */
export function NewTwinHost() {
  const { open, set } = useNewTwinCard();
  const mobile = useMobile();
  // Leaving the workspace (signing out) leaves no card open for the next time it is shown.
  useEffect(() => () => useNewTwinCard.getState().set(false), []);
  return (
    <Dialog
      open={open}
      onOpenChange={set}
      title="新建分身"
      variant={mobile ? 'sheet' : 'center'}
      className="new-twin"
      inPlace
    >
      <NewTwinForm onCreated={() => set(false)} />
    </Dialog>
  );
}
