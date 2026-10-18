import { useId, useRef, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router';
import { Plus } from 'lucide-react';
import {
  Button,
  Card,
  Dialog,
  Field,
  IconButton,
  Input,
  Stack,
  Text,
  TextLink,
} from '../ui';
import { StageHeader } from './StageHeader';
import { api } from '../../lib/api';
import { usePersonas, type Persona } from '../../stores/personas';

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
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const nameId = useId();
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
          size="lg"
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
      <Dialog
        open={open}
        onOpenChange={changeOpen}
        title="新建分身"
        body="每个分身都有独立的记忆、形象、声音和聊天。"
        variant="fullscreen"
        className="create-twin-sheet"
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
          <TextLink to="/twins" size="sm" onClick={() => changeOpen(false)}>
            返回我的分身
          </TextLink>
          <Stack
            as="form"
            gap={3}
            align="start"
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            <div className="w-full">
              <Field id={nameId} label="分身名字">
                <Input
                  id={nameId}
                  autoFocus
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  maxLength={20}
                  required
                />
              </Field>
            </div>
            <Button type="submit" loading={busy} disabled={!draft.trim()}>
              创建并开始
            </Button>
          </Stack>
          {error && (
            <Text role="alert" tone="danger">
              {error}
            </Text>
          )}
        </div>
      </Dialog>
    </>
  );
}
