import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from 'react';
import { Check, ChevronDown } from 'lucide-react';
import {
  AvatarFrame,
  Dialog,
  type DialogAnchor,
  Input,
  PlainButton,
  Row,
  Stack,
  Text,
  TextLink,
} from '../ui';
import { personaUrl } from '../../lib/persona';
import { useManagesCurrent } from '../../stores/access';
import { usePersonas, type Persona } from '../../stores/personas';
import { featureOn, useAuth } from '../../stores/auth';
import { useMobile } from '../../lib/useMobile';
import { useOpenSystem } from '../../features/admin/SystemDialog';
import { PresetSvg } from '../../features/avatar/presets';
import { useNewTwinCard } from './NewTwin';

export function PersonaPortrait({ persona }: { persona?: Persona }) {
  const [failed, setFailed] = useState<string>();
  const url = persona?.avatar_url
    ? personaUrl(persona.avatar_url, persona.id)
    : undefined;
  // The wrapper carries the size (48px).
  return (
    <span className="persona-portrait block size-12 shrink-0">
      {url && failed !== url ? (
        <AvatarFrame size="fill" outlined decorative={false}>
          <img src={url} alt="" onError={() => setFailed(url)} />
        </AvatarFrame>
      ) : (
        <AvatarFrame size="fill" decorative={false}>
          <PresetSvg preset={persona?.avatar_preset} />
        </AvatarFrame>
      )}
    </span>
  );
}

const SEARCH_FROM = 6;

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
  const button = useRef<HTMLButtonElement>(null);
  const navigating = useRef(false);
  const [localOpen, setLocalOpen] = useState(false);
  const open = controlledOpen ?? localOpen;
  const setOpen = (value: boolean) => {
    setLocalOpen(value);
    onOpenChange?.(value);
  };
  const [anchor, setAnchor] = useState<DialogAnchor>();
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const { id, pendingId, items, refresh, switchTo } = usePersonas();
  // A long team list gets a filter instead of scrolling past everyone.
  const searchable = items.length > SEARCH_FROM;
  const shown = query.trim()
    ? items.filter((persona) =>
        persona.name.toLowerCase().includes(query.trim().toLowerCase()),
      )
    : items;
  const current = items.find((item) => item.id === id);
  const identity = useAuth((state) => state.identity);
  const canManage = useManagesCurrent();
  const openSystem = useOpenSystem();
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
  return (
    <>
      <PlainButton
        ref={button}
        aria-label={label}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-busy={pendingId !== null}
        className={
          className ??
          `flex min-h-11 items-center gap-2 px-3 ${stage ? 'stage-switch' : 'hover:bg-soft'}`
        }
        onClick={() => {
          setError('');
          setQuery('');
          navigating.current = false;
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
      </PlainButton>
      <Dialog
        open={open}
        onOpenChange={setOpen}
        title="切换分身"
        body="每个分身都有独立的记忆、形象、声音和聊天。"
        popover={!mobile}
        anchor={mobile ? undefined : (anchor ?? {})}
        className={mobile ? 'persona-sheet' : 'persona-popover'}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          if (!navigating.current)
            (returnFocus?.current ?? button.current)?.focus();
        }}
      >
        <Stack gap={3}>
          {searchable && (
            <Input
              type="search"
              aria-label="搜索分身"
              placeholder="搜索分身"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          )}
          {searchable && !shown.length && (
            <Text size="sm" tone="secondary">
              没有叫这个名字的分身
            </Text>
          )}
          {shown.map((persona) => (
            <PlainButton
              key={persona.id}
              className={`persona-row flex w-full items-center gap-3 p-3 text-left ${persona.id === (pendingId ?? id) ? 'bg-primary text-canvas' : 'bg-surface text-primary'}`}
              onClick={() => {
                setOpen(false);
                switchTo(persona.id);
              }}
            >
              <PersonaPortrait persona={persona} />
              <span className="min-w-0 flex-1">
                <Text
                  as="span"
                  size="xl"
                  tone="inherit"
                  truncate
                  className="persona-name block"
                >
                  {persona.name}
                </Text>
                <Text as="span" size="sm" tone="inherit" className="block">
                  {persona.sources} 条记忆
                </Text>
                {identity?.admin &&
                  persona.owner &&
                  persona.owner !== identity.email && (
                    <Text
                      as="span"
                      size="xs"
                      tone="inherit"
                      truncate
                      className="block"
                    >
                      {persona.owner}
                    </Text>
                  )}
              </span>
              {persona.id === (pendingId ?? id) && (
                <Check aria-label="当前分身" className="size-5" />
              )}
            </PlainButton>
          ))}
          <Row gap={4} wrap>
            {/* The twin's own pages are reached from here: the side bar is about the team. */}
            {[
              ...(canManage ? [{ to: '/profile', title: '档案' }] : []),
              ...(featureOn(identity, 'work')
                ? [{ to: '/work', title: '工作' }]
                : []),
              { to: '/team', title: '团队' },
              { to: '/library', title: '录音库' },
              { to: '/team', title: '全部分身' },
            ].map(({ to, title }) => (
              <TextLink
                key={to}
                to={to}
                onClick={() => {
                  navigating.current = true;
                  setOpen(false);
                }}
              >
                {title}
              </TextLink>
            ))}
            {/* The card opens over the page in view rather than taking the person to the twins page. */}
            <TextLink
              onClick={() => {
                navigating.current = true;
                setOpen(false);
                useNewTwinCard.getState().set(true);
              }}
            >
              ＋ 新建分身
            </TextLink>
            {identity?.admin && (
              <TextLink
                onClick={() => {
                  navigating.current = true;
                  setOpen(false);
                  openSystem();
                }}
              >
                系统
              </TextLink>
            )}
          </Row>
          {error && (
            <Text role="alert" tone="danger">
              {error}
            </Text>
          )}
        </Stack>
      </Dialog>
    </>
  );
}
