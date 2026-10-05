import { AnimatePresence } from 'motion/react';
import { X } from 'lucide-react';
import { useEffect } from 'react';
import { create } from 'zustand';
import { DragDismiss } from '../motion';
import { IconButton, toneClasses, type Tone } from './controls';
import { cn } from '../../lib/utils';
import { useMotionPreset } from '../../design/motion';

type ToastMessage = {
  id: number;
  message: string;
  tone: Tone;
  duration: number;
};
let nextId = 0;
const useToasts = create<{
  items: ToastMessage[];
  add: (item: ToastMessage) => void;
  remove: (id: number) => void;
}>((set) => ({
  items: [],
  add: (item) => set((state) => ({ items: [...state.items.slice(-3), item] })),
  remove: (id) =>
    set((state) => ({ items: state.items.filter((item) => item.id !== id) })),
}));

export function toast(
  message: string,
  tone: Tone = 'neutral',
  duration = 5000,
) {
  const id = ++nextId;
  useToasts.getState().add({ id, message, tone, duration });
  return () => useToasts.getState().remove(id);
}

function Toast({ item }: { item: ToastMessage }) {
  const remove = useToasts((state) => state.remove);
  const { reduced, exit } = useMotionPreset();
  useEffect(() => {
    if (item.duration <= 0) return;
    const timer = setTimeout(() => remove(item.id), item.duration);
    return () => clearTimeout(timer);
  }, [item, remove]);
  return (
    <DragDismiss
      onDismiss={() => remove(item.id)}
      initial={{ opacity: 0, y: reduced ? 0 : 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, transition: exit }}
      className="pointer-events-auto flex items-center gap-3 rounded-lg border border-border bg-surface p-3 shadow-elevation-2"
    >
      <p className={cn('flex-1', toneClasses[item.tone])}>{item.message}</p>
      <IconButton label="关闭通知" onClick={() => remove(item.id)}>
        <X className="size-4" />
      </IconButton>
    </DragDismiss>
  );
}

export function ToastViewport() {
  // Announce via the live region only; arriving toasts must never move focus.
  const items = useToasts((state) => state.items);
  return (
    <>
      <div
        className="sr-only"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        {items.at(-1)?.message}
      </div>
      <div
        aria-label="通知"
        className="pointer-events-none fixed right-4 bottom-5 left-4 z-60 flex flex-col gap-2 md:left-auto md:w-80"
      >
        <AnimatePresence initial={false}>
          {items.map((item) => (
            <Toast key={item.id} item={item} />
          ))}
        </AnimatePresence>
      </div>
    </>
  );
}
