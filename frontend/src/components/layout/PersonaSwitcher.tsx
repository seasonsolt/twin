import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
  type RefObject,
} from 'react';
import { Link, useNavigate } from 'react-router';
import { Check, ChevronDown, UsersRound } from 'lucide-react';
import { Dialog } from '../ui';
import { personaUrl } from '../../lib/persona';
import { usePersonas, type Persona } from '../../stores/personas';
import { useAuth } from '../../stores/auth';
import { useMobile } from '../../lib/useMobile';

export function PersonaPortrait({ persona }: { persona?: Persona }) {
  const [failed, setFailed] = useState<string>();
  const url = persona?.avatar_url
    ? personaUrl(persona.avatar_url, persona.id)
    : undefined;
  return url && failed !== url ? (
    <img
      src={url}
      alt=""
      onError={() => setFailed(url)}
      className="persona-portrait size-12 shrink-0 rounded-full border-2 border-canvas object-cover"
    />
  ) : (
    <span
      className="persona-portrait persona-name grid size-12 shrink-0 place-items-center rounded-full bg-soft text-2xl text-primary"
      aria-hidden
    >
      {Array.from(persona?.name || '本人')[0]}
    </span>
  );
}

export function PersonaSwitcher({
  stage = false,
  trigger,
  label = '切换分身',
  className,
  open: controlledOpen,
  onOpenChange,
  returnFocus,
}: {
  stage?: boolean;
  trigger?: ReactNode;
  label?: string;
  className?: string;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  returnFocus?: RefObject<HTMLButtonElement | null>;
}) {
  const mobile = useMobile();
  const navigate = useNavigate();
  const button = useRef<HTMLButtonElement>(null);
  const [localOpen, setLocalOpen] = useState(false);
  const open = controlledOpen ?? localOpen;
  const setOpen = (value: boolean) => {
    setLocalOpen(value);
    onOpenChange?.(value);
  };
  const [anchor, setAnchor] = useState<CSSProperties>();
  const [error, setError] = useState('');
  const { id, items, refresh, switchTo } = usePersonas();
  const current = items.find((item) => item.id === id);
  const identity = useAuth((state) => state.identity);
  useEffect(() => {
    if (!open) return;
    void refresh().catch((failure: unknown) =>
      setError(failure instanceof Error ? failure.message : '无法加载分身'),
    );
  }, [open, refresh]);
  useEffect(() => {
    if (mobile || !open) return;
    const position = () => {
      const rect = (
        returnFocus?.current ?? button.current
      )?.getBoundingClientRect();
      if (!rect) return;
      const width = Math.min(360, window.innerWidth - 48);
      setAnchor({
        left: Math.max(24, Math.min(rect.left, window.innerWidth - width - 24)),
        ...(rect.top > window.innerHeight / 2
          ? {
              top: 'auto',
              bottom: Math.max(24, window.innerHeight - rect.bottom),
            }
          : { top: rect.bottom + 8, bottom: 'auto' }),
        width,
        maxHeight:
          rect.top > window.innerHeight / 2
            ? window.innerHeight - 48
            : window.innerHeight - rect.bottom - 32,
      });
    };
    position();
    window.addEventListener('resize', position);
    window.addEventListener('scroll', position, true);
    return () => {
      window.removeEventListener('resize', position);
      window.removeEventListener('scroll', position, true);
    };
  }, [mobile, open, returnFocus]);
  if (stage && mobile)
    return (
      <button
        type="button"
        className="stage-all"
        aria-label="全部分身"
        onClick={() => navigate('/twins')}
      >
        <UsersRound size={22} aria-hidden />
      </button>
    );
  return (
    <>
      <button
        ref={button}
        type="button"
        aria-label={label}
        aria-haspopup="dialog"
        aria-expanded={open}
        className={
          className ??
          `flex min-h-11 items-center gap-2 rounded-full px-3 text-base ${stage ? 'stage-switch' : 'hover:bg-soft'}`
        }
        onClick={() => {
          setError('');
          setOpen(true);
        }}
      >
        {trigger ?? (
          <>
            {!stage && <PersonaPortrait persona={current} />}
            <span className={stage ? '' : 'persona-name max-w-52 truncate'}>
              {stage ? '切换' : current?.name || '本人'}
            </span>
            <ChevronDown className="size-4" aria-hidden />
          </>
        )}
      </button>
      <Dialog
        open={open}
        onOpenChange={setOpen}
        title="切换分身"
        body="每个分身都有独立的记忆、形象、声音和聊天。"
        popover={!mobile}
        style={!mobile ? { ...anchor, translate: 'none' } : undefined}
        className={`${mobile ? 'persona-sheet' : 'persona-popover'} [&_button]:min-h-11 [&_button]:min-w-11`}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          (returnFocus?.current ?? button.current)?.focus();
        }}
      >
        <div className="space-y-3">
          {items.map((persona) => (
            <button
              key={persona.id}
              type="button"
              className={`persona-row flex w-full items-center gap-3 rounded-full p-3 text-left ${persona.id === id ? 'bg-primary text-canvas' : 'bg-surface text-primary'}`}
              onClick={() => {
                setOpen(false);
                switchTo(persona.id);
              }}
            >
              <PersonaPortrait persona={persona} />
              <span className="min-w-0 flex-1">
                <span className="persona-name block truncate text-xl">
                  {persona.name}
                </span>
                <span className="block text-sm">{persona.sources} 条记忆</span>
                {identity?.admin &&
                  persona.owner &&
                  persona.owner !== identity.email && (
                    <span className="block truncate text-xs">
                      {persona.owner}
                    </span>
                  )}
              </span>
              {persona.id === id && (
                <Check aria-label="当前分身" className="size-5" />
              )}
            </button>
          ))}
          <div className="flex flex-wrap gap-4">
            <Link
              to="/twins"
              className="min-h-11 text-accent underline"
              onClick={() => setOpen(false)}
            >
              全部分身
            </Link>
            <Link
              to="/twins?create=1"
              className="min-h-11 text-accent underline"
              onClick={() => setOpen(false)}
            >
              新建分身
            </Link>
          </div>
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
