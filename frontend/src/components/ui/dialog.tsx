import * as RadixDialog from '@radix-ui/react-dialog';
import { AnimatePresence, motion, type Transition } from 'motion/react';
import { X } from 'lucide-react';
import {
  createContext,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type ComponentType,
  type ReactNode,
  type CSSProperties,
} from 'react';
import { crossfade, exitDurations, useMotionPreset } from '../../design/motion';
import { Button, IconButton, Input, type Tone } from './controls';
import { cn } from '../../lib/utils';

export type DialogAnchor = Pick<
  CSSProperties,
  'left' | 'top' | 'bottom' | 'width' | 'maxHeight'
>;

export function Dialog({
  open,
  onOpenChange,
  title,
  body,
  children,
  onCloseAutoFocus,
  onOpenAutoFocus,
  onInteractOutside,
  onEscapeKeyDown,
  className,
  exitTransition,
  popover = false,
  variant = 'center',
  anchor,
  inPlace = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  body?: string;
  children?: ReactNode;
  onCloseAutoFocus?: (event: Event) => void;
  onOpenAutoFocus?: (event: Event) => void;
  onInteractOutside?: RadixDialog.DialogContentProps['onInteractOutside'];
  onEscapeKeyDown?: RadixDialog.DialogContentProps['onEscapeKeyDown'];
  className?: string;
  exitTransition?: Transition;
  popover?: boolean;
  /**
   * center: a box in the middle of the screen. sheet: pinned to the bottom edge, full width (for phones).
   * fullscreen: covers the whole window. drawer: a column at the top right, beside the page it explains.
   * side: a full-height layer at the right edge, for reading something beside the page (the evidence of an answer);
   * closing it leaves the page where it was.
   * Only center is placed by translation; the others are placed by their edges, so no page rule has to undo it.
   */
  variant?: 'center' | 'sheet' | 'fullscreen' | 'drawer' | 'side';
  /** For a popover placed next to its trigger: the position the page measured. Replaces the centring. */
  anchor?: DialogAnchor;
  /** A short task done on the page itself: the page behind is only dimmed, not blurred, so it stays in view. */
  inPlace?: boolean;
}) {
  const { reduced, transition, exit: fade } = useMotionPreset('gentle');
  const exit = { ...fade, duration: exitDurations.dialog };
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange} modal={!popover}>
      <RadixDialog.Portal forceMount>
        <AnimatePresence>
          {open && !popover && (
            <RadixDialog.Overlay key="overlay" forceMount asChild>
              <motion.div
                key="overlay"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={exit}
                // Beside a side layer the page stays readable: what it is read against is right there.
                className={cn(
                  'fixed inset-0 z-40',
                  variant === 'side' || inPlace
                    ? 'bg-black/10'
                    : 'bg-black/25 backdrop-blur-sm',
                )}
              />
            </RadixDialog.Overlay>
          )}
          {open && (
            <RadixDialog.Content
              key="dialog"
              forceMount
              asChild
              onCloseAutoFocus={onCloseAutoFocus}
              onOpenAutoFocus={onOpenAutoFocus}
              onInteractOutside={onInteractOutside}
              onEscapeKeyDown={onEscapeKeyDown}
              {...(!body ? { 'aria-describedby': undefined } : {})}
            >
              <motion.div
                key="dialog"
                style={anchor && { ...anchor, translate: 'none' }}
                initial={
                  variant === 'side'
                    ? { opacity: 0, x: reduced ? 0 : 24 }
                    : { opacity: 0, scale: reduced ? 1 : 0.96 }
                }
                animate={
                  variant === 'side'
                    ? { opacity: 1, x: 0 }
                    : { opacity: 1, scale: 1 }
                }
                exit={{
                  opacity: 0,
                  ...(variant === 'side'
                    ? { x: reduced ? 0 : 16 }
                    : { scale: reduced ? 1 : 0.98 }),
                  transition: exitTransition ?? exit,
                }}
                transition={transition}
                className={cn(
                  'fixed z-50 overflow-y-auto border border-border bg-canvas text-primary shadow-elevation-3',
                  {
                    center:
                      'top-1/2 left-1/2 max-h-[85dvh] w-[min(440px,calc(100%_-_32px))] -translate-x-1/2 -translate-y-1/2 rounded-lg p-6',
                    sheet:
                      'top-auto right-0 bottom-0 left-0 max-h-[85dvh] w-full rounded-t-lg p-4 pb-[max(16px,env(safe-area-inset-bottom))]',
                    fullscreen:
                      'inset-0 h-dvh max-h-dvh w-full rounded-none border-0 p-4',
                    drawer:
                      'top-24 right-6 max-h-[calc(100dvh_-_120px)] w-[min(400px,calc(100%_-_48px))] rounded-lg p-6',
                    side: 'top-0 right-0 bottom-0 h-dvh max-h-dvh w-[min(440px,100%)] rounded-l-lg p-6 pb-[max(24px,env(safe-area-inset-bottom))]',
                  }[variant],
                  className,
                )}
              >
                <div className="mb-3 flex items-center justify-between gap-4">
                  <RadixDialog.Title className="text-lg font-semibold">
                    {title}
                  </RadixDialog.Title>
                  <RadixDialog.Close asChild>
                    <IconButton label="关闭">
                      <X className="size-4" />
                    </IconButton>
                  </RadixDialog.Close>
                </div>
                {body && (
                  <RadixDialog.Description className="mb-5 text-secondary">
                    {body}
                  </RadixDialog.Description>
                )}
                {children}
              </motion.div>
            </RadixDialog.Content>
          )}
        </AnimatePresence>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

export interface ConfirmOptions {
  title: string;
  body: string;
  confirmLabel: string;
  tone?: 'primary' | 'danger';
}
type Request = {
  options: ConfirmOptions;
  resolve: (result: boolean) => void;
  focus: Element | null;
};
const ConfirmContext = createContext<
  ((options: ConfirmOptions) => Promise<boolean>) | null
>(null);

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const queue = useRef<Request[]>([]);
  const cancelButton = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef<Element | null>(null);
  const [request, setRequest] = useState<Request | null>(null);
  const confirm = (options: ConfirmOptions) =>
    new Promise<boolean>((resolve) => {
      const next = { options, resolve, focus: document.activeElement };
      queue.current.push(next);
      if (queue.current.length === 1) setRequest(next);
    });
  const finish = (result: boolean) => {
    const finished = queue.current.shift();
    if (!finished) return;
    restoreFocus.current = finished.focus;
    finished.resolve(result);
    setRequest(queue.current[0] ?? null);
    if (queue.current.length) cancelButton.current?.focus();
  };
  useEffect(
    () => () => {
      queue.current.splice(0).forEach((pending) => pending.resolve(false));
    },
    [],
  );
  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <Dialog
        open={request !== null}
        onOpenChange={(open) => {
          if (!open) finish(false);
        }}
        title={request?.options.title ?? ''}
        body={request?.options.body ?? ''}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          cancelButton.current?.focus();
        }}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          const target = restoreFocus.current;
          if (
            !queue.current.length &&
            target instanceof HTMLElement &&
            target.isConnected
          )
            target.focus();
        }}
      >
        <div className="flex justify-end gap-2">
          <Button
            ref={cancelButton}
            variant="secondary"
            onClick={() => finish(false)}
          >
            取消
          </Button>
          <Button variant="primary" onClick={() => finish(true)}>
            {request?.options.confirmLabel}
          </Button>
        </div>
      </Dialog>
    </ConfirmContext.Provider>
  );
}

export function useConfirm() {
  const confirm = useContext(ConfirmContext);
  if (!confirm) throw new Error('useConfirm requires ConfirmProvider');
  return confirm;
}

export interface SettingsSection {
  key: string;
  label: string;
  /** Starts a new group in the menu, under this heading. */
  group?: string;
  icon?: ComponentType<{ className?: string; 'aria-hidden'?: boolean }>;
  /** A short state after the label, such as 异常 or 已关闭. Only danger draws the eye (a dot); the rest stay quiet. */
  status?: { label: string; tone?: Tone };
}

/**
 * A large dialog with its own menu, for settings that sit on top of the current page rather than replacing it:
 * closing it returns to where the person was. Menu on the left on wide screens; on phones it fills the screen and
 * the menu becomes a row of chips under the title.
 */
export function SettingsDialog({
  open,
  onOpenChange,
  title,
  note,
  sections,
  active,
  onSelect,
  actions,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The dialog's name, above the menu. */
  title: string;
  /** One quiet line under the title, such as who can see it. */
  note?: string;
  sections: SettingsSection[];
  active: string;
  onSelect: (key: string) => void;
  /** Buttons beside the section heading, such as a refresh. */
  actions?: ReactNode;
  children: ReactNode;
}) {
  const { reduced, transition } = useMotionPreset('gentle');
  const exit = { ...crossfade, duration: exitDurations.dialog };
  const current = sections.find((section) => section.key === active);
  const menu = useRef<HTMLUListElement>(null);
  // On phones the menu is a scrolling row: keep the open section's chip in view.
  // Positions come from layout (offsetLeft), not the screen, so the opening scale does not throw them off; again
  // when the fonts load or a status arrives, since the chips widen with them.
  const statuses = sections.map((section) => section.status?.label).join();
  useEffect(() => {
    if (!open) return;
    let live = true;
    const center = () => {
      const list = menu.current;
      const chip = list?.querySelector<HTMLElement>('[aria-current="page"]');
      if (!live || !list || !chip || list.scrollWidth <= list.clientWidth)
        return;
      list.scrollLeft =
        chip.offsetLeft -
        list.offsetLeft -
        (list.clientWidth - chip.offsetWidth) / 2;
    };
    const frame = requestAnimationFrame(center);
    void document.fonts?.ready.then(center);
    return () => {
      live = false;
      cancelAnimationFrame(frame);
    };
  }, [open, active, statuses]);
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal forceMount>
        <AnimatePresence>
          {open && (
            <RadixDialog.Overlay key="overlay" forceMount asChild>
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={exit}
                className="fixed inset-0 z-40 bg-black/10 backdrop-blur-sm"
              />
            </RadixDialog.Overlay>
          )}
          {open && (
            <RadixDialog.Content
              key="settings"
              forceMount
              asChild
              aria-describedby={undefined}
              // Focus the dialog itself, not the first menu item: no ring on a choice nobody made yet. Tab then
              // goes through the menu.
              onOpenAutoFocus={(event) => {
                event.preventDefault();
                (event.currentTarget as HTMLElement | null)?.focus();
              }}
              tabIndex={-1}
            >
              <motion.div
                initial={{ opacity: 0, scale: reduced ? 1 : 0.98 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{
                  opacity: 0,
                  scale: reduced ? 1 : 0.99,
                  transition: exit,
                }}
                transition={transition}
                className="fixed inset-0 z-50 flex flex-col bg-surface text-primary outline-none md:inset-auto md:top-1/2 md:left-1/2 md:h-[min(720px,calc(100dvh_-_48px))] md:w-[min(1040px,calc(100%_-_48px))] md:-translate-x-1/2 md:-translate-y-1/2 md:flex-row md:overflow-hidden md:rounded-lg md:border md:border-border md:shadow-elevation-3"
              >
                <nav
                  aria-label={title}
                  className="flex shrink-0 flex-col border-b border-border bg-canvas md:w-[224px] md:border-r md:border-b-0 md:px-3 md:py-5"
                >
                  <div className="flex items-center justify-between gap-3 px-4 pt-4 md:block md:px-3 md:pt-0">
                    <div>
                      <RadixDialog.Title className="text-xl font-semibold">
                        {title}
                      </RadixDialog.Title>
                      {note && <p className="text-xs text-tertiary">{note}</p>}
                    </div>
                    <RadixDialog.Close asChild>
                      <IconButton label="关闭" className="md:hidden">
                        <X className="size-5" />
                      </IconButton>
                    </RadixDialog.Close>
                  </div>
                  <ul
                    ref={menu}
                    className="flex gap-1 overflow-x-auto px-3 py-3 md:mt-4 md:flex-col md:overflow-visible md:p-0"
                  >
                    {sections.map((section) => {
                      const selected = section.key === active;
                      const Icon = section.icon;
                      return (
                        <li key={section.key} className="shrink-0">
                          {section.group && (
                            <p className="hidden px-3 pt-4 pb-1.5 text-xs text-tertiary md:block">
                              {section.group}
                            </p>
                          )}
                          <button
                            type="button"
                            aria-current={selected ? 'page' : undefined}
                            onClick={() => onSelect(section.key)}
                            className={cn(
                              'flex min-h-11 w-full items-center gap-2.5 rounded-full px-3 text-left text-base whitespace-nowrap transition-colors hover:bg-soft focus-visible:outline-2 focus-visible:outline-accent md:min-h-10 md:rounded-sm',
                              selected &&
                                'bg-surface font-medium shadow-elevation-1 hover:bg-surface',
                            )}
                          >
                            {Icon && (
                              <Icon aria-hidden className="size-4 shrink-0" />
                            )}
                            {section.label}
                            {section.status && (
                              <span
                                className={cn(
                                  'ml-auto flex items-center gap-1.5 pl-2 text-xs',
                                  section.status.tone === 'danger'
                                    ? 'text-danger'
                                    : 'text-tertiary',
                                )}
                              >
                                {section.status.tone === 'danger' && (
                                  <span
                                    aria-hidden
                                    className="size-1.5 rounded-full bg-danger"
                                  />
                                )}
                                {section.status.label}
                              </span>
                            )}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </nav>
                <section className="flex min-h-0 min-w-0 flex-1 flex-col">
                  <header className="flex items-center gap-3 border-b border-border px-4 py-3 md:px-7 md:py-4">
                    <h3 className="min-w-0 flex-1 truncate text-xl font-semibold">
                      {current?.label}
                    </h3>
                    {actions}
                    <RadixDialog.Close asChild>
                      <IconButton
                        label="关闭"
                        className="hidden md:inline-flex"
                      >
                        <X className="size-5" />
                      </IconButton>
                    </RadixDialog.Close>
                  </header>
                  <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 md:px-7 md:py-6">
                    {children}
                  </div>
                </section>
              </motion.div>
            </RadixDialog.Content>
          )}
        </AnimatePresence>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

export interface SearchItem {
  id: string;
  label: string;
  /** One short line after the name: what can be done with it. */
  detail?: string;
  /** A portrait or mark before the name. */
  leading?: ReactNode;
}

/**
 * Find one thing by typing its name and go to it: a field over a short list of matches, ↑↓ to move, Enter to
 * pick. Only the first `limit` matches are listed; typing more narrows them.
 */
export function SearchDialog({
  open,
  onOpenChange,
  title,
  placeholder,
  items,
  onSelect,
  empty,
  limit = 8,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  placeholder: string;
  items: SearchItem[];
  onSelect: (item: SearchItem) => void;
  /** Said when nothing matches what was typed. */
  empty: string;
  limit?: number;
}) {
  const [query, setQuery] = useState('');
  const [at, setAt] = useState(0);
  const listId = useId();
  useEffect(() => {
    if (!open) return;
    setQuery('');
    setAt(0);
  }, [open]);
  const wanted = query.trim().toLocaleLowerCase();
  const shown = items
    .filter((item) => item.label.toLocaleLowerCase().includes(wanted))
    .slice(0, limit);
  const current = Math.min(at, shown.length - 1);
  const pick = (item: SearchItem | undefined) => {
    if (!item) return;
    onOpenChange(false);
    onSelect(item);
  };
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      className="search-dialog"
    >
      <div className="flex flex-col gap-2">
        <Input
          autoFocus
          type="search"
          role="combobox"
          aria-label={title}
          aria-expanded={shown.length > 0}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={
            current >= 0 ? `${listId}-${shown[current].id}` : undefined
          }
          placeholder={placeholder}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setAt(0);
          }}
          onKeyDown={(event) => {
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
              event.preventDefault();
              const step = event.key === 'ArrowDown' ? 1 : -1;
              setAt(
                (current + step + shown.length) % Math.max(1, shown.length),
              );
            } else if (event.key === 'Enter') {
              event.preventDefault();
              pick(shown[current]);
            }
          }}
        />
        {shown.length ? (
          <ul
            id={listId}
            role="listbox"
            aria-label={title}
            className="flex flex-col"
          >
            {shown.map((item, index) => (
              <li
                key={item.id}
                id={`${listId}-${item.id}`}
                role="option"
                aria-selected={index === current}
                onMouseEnter={() => setAt(index)}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => pick(item)}
                className={cn(
                  'flex min-h-11 cursor-pointer items-center gap-3 rounded-sm px-2',
                  index === current && 'bg-soft',
                )}
              >
                {item.leading}
                <span className="min-w-0 flex-1 truncate font-medium">
                  {item.label}
                </span>
                {item.detail && (
                  <span className="shrink-0 text-xs text-secondary">
                    {item.detail}
                  </span>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p role="status" className="px-2 py-3 text-sm text-secondary">
            {empty}
          </p>
        )}
      </div>
    </Dialog>
  );
}

export interface AskItem extends SearchItem {
  /** What pressing it does, as a short phrase after the name (问分身, 看档案). */
  action?: string;
  /** A mark of how well something is known, or any small sign, after the name. */
  sign?: ReactNode;
}

export interface AskSection {
  id: string;
  title: string;
  /** How many there are, shown beside the title. */
  count?: number;
  /** Answers shown as they are, above the rows: not picked, only read. */
  cards?: ReactNode;
  items?: AskItem[];
  /** One line under the section. */
  note?: string;
}

/**
 * Ask one question of the whole team and read the answers in sections, from the one that can be used as it stands to
 * the one that has to be asked again. The field is the page's (`query`), because what it lists is found elsewhere
 * (`sections`, which the page fills as the answer arrives); ↑↓ move over every row of every section, Enter picks.
 * `busy` says the search is under way, `notice` that part of it could not be done, `empty` that nothing was found.
 */
export function AskDialog({
  open,
  onOpenChange,
  title,
  placeholder,
  query,
  onQueryChange,
  sections,
  onSelect,
  empty,
  busy = false,
  notice,
  hint,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  placeholder: string;
  query: string;
  onQueryChange: (query: string) => void;
  sections: AskSection[];
  onSelect: (item: AskItem) => void;
  empty: string;
  busy?: boolean;
  notice?: string;
  /** The keys, shown under the list on a desktop. */
  hint?: string;
}) {
  const [at, setAt] = useState(0);
  const listId = useId();
  useEffect(() => {
    if (open) setAt(0);
  }, [open]);
  const rows = sections.flatMap((section) => section.items ?? []);
  const current = Math.min(at, rows.length - 1);
  const shown = sections.filter(
    (section) => section.cards || section.items?.length,
  );
  // Each section's rows are a list of their own: the heading and the answers above them are not options.
  const lists = shown
    .filter((section) => section.items?.length)
    .map((section) => `${listId}-${section.id}`);
  const pick = (item: AskItem | undefined) => {
    if (!item) return;
    onOpenChange(false);
    onSelect(item);
  };
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      className="search-dialog"
    >
      <div className="flex flex-col gap-3">
        <Input
          autoFocus
          type="search"
          role="combobox"
          aria-label={title}
          aria-expanded={rows.length > 0}
          aria-controls={lists.join(' ') || undefined}
          aria-autocomplete="list"
          aria-activedescendant={
            current >= 0 ? `${listId}-${rows[current].id}` : undefined
          }
          placeholder={placeholder}
          value={query}
          onChange={(event) => {
            onQueryChange(event.target.value);
            setAt(0);
          }}
          onKeyDown={(event) => {
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
              event.preventDefault();
              const step = event.key === 'ArrowDown' ? 1 : -1;
              setAt((current + step + rows.length) % Math.max(1, rows.length));
            } else if (event.key === 'Enter') {
              event.preventDefault();
              pick(rows[current]);
            }
          }}
        />
        {notice && (
          <p role="status" className="text-sm text-secondary">
            {notice}
          </p>
        )}
        {shown.map((section) => (
          <section
            key={section.id}
            aria-labelledby={`${listId}-${section.id}-title`}
            className="flex flex-col gap-1"
          >
            <h3
              id={`${listId}-${section.id}-title`}
              className="flex items-baseline gap-2 px-2 text-sm font-semibold text-secondary"
            >
              {section.title}
              {section.count !== undefined && (
                <span className="font-normal">{section.count}</span>
              )}
            </h3>
            {section.cards && (
              <div className="flex flex-col gap-2">{section.cards}</div>
            )}
            {section.items?.length ? (
              <div
                id={`${listId}-${section.id}`}
                role="listbox"
                aria-labelledby={`${listId}-${section.id}-title`}
                className="flex flex-col gap-1"
              >
                {section.items.map((item) => {
                  const index = rows.indexOf(item);
                  return (
                    <div
                      key={item.id}
                      id={`${listId}-${item.id}`}
                      role="option"
                      aria-selected={index === current}
                      onMouseEnter={() => setAt(index)}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => pick(item)}
                      className={cn(
                        'flex min-h-11 cursor-pointer items-center gap-3 rounded-sm px-2 py-1',
                        index === current && 'bg-soft',
                      )}
                    >
                      {item.leading}
                      <span className="flex min-w-0 flex-1 flex-col">
                        <span className="truncate font-medium">
                          {item.label}
                        </span>
                        {item.detail && (
                          <span className="truncate text-xs text-secondary">
                            {item.detail}
                          </span>
                        )}
                      </span>
                      {item.sign}
                      {item.action && (
                        <span className="shrink-0 text-sm font-medium text-accent">
                          {item.action}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : null}
            {section.note && (
              <p className="px-2 text-xs text-secondary">{section.note}</p>
            )}
          </section>
        ))}
        {busy ? (
          <p role="status" className="px-2 text-sm text-secondary">
            正在找…
          </p>
        ) : (
          !shown.length &&
          empty &&
          query.trim().length >= 2 && (
            <p role="status" className="px-2 py-3 text-sm text-secondary">
              {empty}
            </p>
          )
        )}
        {hint && rows.length > 0 && (
          <p aria-hidden className="text-xs text-secondary max-md:hidden">
            {hint}
          </p>
        )}
      </div>
    </Dialog>
  );
}
