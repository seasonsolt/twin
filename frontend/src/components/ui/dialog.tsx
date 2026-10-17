import * as RadixDialog from '@radix-ui/react-dialog';
import { AnimatePresence, motion, type Transition } from 'motion/react';
import { X } from 'lucide-react';
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ComponentType,
  type ReactNode,
  type CSSProperties,
} from 'react';
import { crossfade, exitDurations, useMotionPreset } from '../../design/motion';
import { Button, IconButton, type Tone } from './controls';
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
  /** center: a box in the middle of the screen. sheet: pinned to the bottom edge, full width (for phones). */
  variant?: 'center' | 'sheet';
  /** For a popover placed next to its trigger: the position the page measured. Replaces the centring. */
  anchor?: DialogAnchor;
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
                className="fixed inset-0 z-40 bg-black/25 backdrop-blur-sm"
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
                initial={{ opacity: 0, scale: reduced ? 1 : 0.96 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{
                  opacity: 0,
                  scale: reduced ? 1 : 0.98,
                  transition: exitTransition ?? exit,
                }}
                transition={transition}
                className={cn(
                  'fixed z-50 max-h-[85dvh] overflow-y-auto border border-border bg-canvas text-primary shadow-elevation-3',
                  variant === 'sheet'
                    ? 'top-auto right-0 bottom-0 left-0 w-full rounded-t-lg p-4 pb-[max(16px,env(safe-area-inset-bottom))]'
                    : 'top-1/2 left-1/2 w-[min(440px,calc(100%_-_32px))] -translate-x-1/2 -translate-y-1/2 rounded-lg p-6',
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
            >
              <motion.div
                initial={{ opacity: 0, scale: reduced ? 1 : 0.98 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: reduced ? 1 : 0.99, transition: exit }}
                transition={transition}
                className="fixed inset-0 z-50 flex flex-col bg-surface text-primary md:inset-auto md:top-1/2 md:left-1/2 md:h-[min(720px,calc(100dvh_-_48px))] md:w-[min(1040px,calc(100%_-_48px))] md:-translate-x-1/2 md:-translate-y-1/2 md:flex-row md:overflow-hidden md:rounded-lg md:border md:border-border md:shadow-elevation-3"
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
                      {note && (
                        <p className="text-xs text-tertiary">{note}</p>
                      )}
                    </div>
                    <RadixDialog.Close asChild>
                      <IconButton label="关闭" className="md:hidden">
                        <X className="size-5" />
                      </IconButton>
                    </RadixDialog.Close>
                  </div>
                  <ul className="flex gap-1 overflow-x-auto px-3 py-3 md:mt-4 md:flex-col md:overflow-visible md:p-0">
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
                      <IconButton label="关闭" className="hidden md:inline-flex">
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
