import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router';
import { Plus } from 'lucide-react';
import {
  Button,
  Card,
  Dialog,
  Field,
  IconButton,
  Input,
  Row,
  Stack,
  Text,
  type DialogAnchor,
} from '../ui';
import { useMobile } from '../../lib/useMobile';
import { api } from '../../lib/api';
import { usePersonas, type Persona } from '../../stores/personas';
import { useAuth } from '../../stores/auth';

export function NewTwin({
  initialOpen = false,
  children = '新建分身',
  variant = 'button',
  onOpenChange,
}: {
  initialOpen?: boolean;
  /** The trigger's content (not used by the rail's round plus button). */
  children?: ReactNode;
  /** button: a primary button; rail: the round plus in the side rail; card: the dashed tile in the twins grid. */
  variant?: 'button' | 'rail' | 'card';
  onOpenChange?: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(initialOpen);
  // Someone's first twin is most likely of themselves: start from the name their company account gives.
  const [draft, setDraft] = useState(() =>
    initialOpen
      ? Array.from(useAuth.getState().identity?.name ?? '')
          .slice(0, 20)
          .join('')
      : '',
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const nameId = useId();
  const mobile = useMobile();
  const [anchor, setAnchor] = useState<DialogAnchor>();
  // Beside the rail's plus: to its right, level with it, so the card comes out of what was clicked.
  useEffect(() => {
    if (mobile || !open || variant !== 'rail') {
      setAnchor(undefined);
      return;
    }
    const place = () => {
      const rect = trigger.current?.getBoundingClientRect();
      if (!rect) return;
      const width = Math.min(360, window.innerWidth - rect.right - 32);
      setAnchor(
        rect.top > window.innerHeight / 2
          ? {
              left: rect.right + 16,
              top: 'auto',
              bottom: Math.max(16, window.innerHeight - rect.bottom),
              width,
            }
          : { left: rect.right + 16, top: rect.top, width },
      );
    };
    place();
    window.addEventListener('resize', place);
    return () => window.removeEventListener('resize', place);
  }, [mobile, open, variant]);
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
  const triggerProps = {
    ref: trigger,
    'aria-haspopup': 'dialog' as const,
    'aria-expanded': open,
    onClick: () => {
      setError('');
      changeOpen(true);
    },
  };
  return (
    <>
      {variant === 'rail' ? (
        <IconButton
          {...triggerProps}
          label="新建分身"
          shape="circle"
          size="md"
          className="rail-new text-primary"
        >
          <Plus aria-hidden className="size-6" />
        </IconButton>
      ) : variant === 'card' ? (
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
      ) : (
        <Button {...triggerProps} size="lg" aria-label="新建分身">
          {children}
        </Button>
      )}
      {/* Made where the person already is: a card beside the rail's plus, in the middle of the page otherwise, from
          the bottom edge on a phone. The work behind stays in view and is there again when it closes. */}
      <Dialog
        open={open}
        onOpenChange={changeOpen}
        title="新建分身"
        variant={mobile ? 'sheet' : 'center'}
        anchor={mobile ? undefined : anchor}
        className="new-twin"
        inPlace
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          trigger.current?.focus();
        }}
      >
        <Stack gap={4}>
          <Stack
            as="form"
            gap={3}
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
            {error && (
              <Text role="alert" size="sm" tone="danger">
                {error}
              </Text>
            )}
          </Stack>
          <Text size="sm" tone="secondary">
            每个分身有独立的记忆和聊天。创建后添加录音或资料，勾出哪位是你，就能开始聊。
          </Text>
        </Stack>
      </Dialog>
    </>
  );
}
