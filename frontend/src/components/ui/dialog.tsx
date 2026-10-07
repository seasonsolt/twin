import * as RadixDialog from '@radix-ui/react-dialog';
import { AnimatePresence, motion, type Transition } from 'motion/react';
import { X } from 'lucide-react';
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type CSSProperties,
} from 'react';
import { exitDurations, useMotionPreset } from '../../design/motion';
import { Button, IconButton } from './controls';
import { cn } from '../../lib/utils';

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
  style,
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
  style?: CSSProperties;
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
                style={style}
                initial={{ opacity: 0, scale: reduced ? 1 : 0.96 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{
                  opacity: 0,
                  scale: reduced ? 1 : 0.98,
                  transition: exitTransition ?? exit,
                }}
                transition={transition}
                className={cn(
                  'fixed top-1/2 left-1/2 z-50 max-h-[85dvh] w-[min(440px,calc(100%_-_32px))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-xl border border-border bg-canvas p-6 text-primary shadow-elevation-3',
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
