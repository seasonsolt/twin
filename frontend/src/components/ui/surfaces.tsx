import { type ComponentProps, type ReactNode } from 'react';
import { motion } from 'motion/react';
import { Inbox } from 'lucide-react';
import { useMotionPreset } from '../../design/motion';
import { Pressable } from '../motion';
import { cn } from '../../lib/utils';
import { toneClasses, type Tone } from './controls';

export function Card({
  interactive = false,
  onClick,
  className,
  children,
}: {
  interactive?: boolean;
  onClick?: () => void;
  className?: string;
  children: ReactNode;
}) {
  const styles = cn(
    'rounded-lg border border-border bg-surface p-5 shadow-card',
    className,
  );
  return interactive ? (
    <Pressable onClick={onClick} className={cn(styles, 'text-left')}>
      {children}
    </Pressable>
  ) : (
    <section className={styles}>{children}</section>
  );
}

export function Badge({
  tone = 'neutral',
  className,
  ...props
}: ComponentProps<'span'> & { tone?: Tone }) {
  return (
    <span
      {...props}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border border-current/15 bg-current/5 px-2.5 py-0.5 text-xs font-medium',
        toneClasses[tone],
        className,
      )}
    />
  );
}

export function Meter({ value, label }: { value: number; label: string }) {
  const { reduced, transition } = useMotionPreset('gentle');
  const percent = Math.max(0, Math.min(100, value));
  return (
    <div className="space-y-2">
      <div className="flex justify-between text-sm">
        <span>{label}</span>
        <span className="text-secondary">{Math.round(percent)}%</span>
      </div>
      <div
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        className="h-2 overflow-hidden rounded-full bg-border"
      >
        {reduced ? (
          <motion.div
            key={percent}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={transition}
            style={{ width: `${percent}%` }}
            className="h-full rounded-full bg-accent"
          />
        ) : (
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${percent}%` }}
            transition={transition}
            className="h-full rounded-full bg-accent"
          />
        )}
      </div>
    </div>
  );
}

export function Skeleton({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div
      {...props}
      aria-hidden
      className={cn('skeleton h-4 rounded-sm', className)}
    />
  );
}

export function EmptyState({
  title,
  body,
  children,
}: {
  title: string;
  body?: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 px-5 py-16 text-center">
      <span className="rounded-xl border border-border bg-surface p-4 text-tertiary">
        <Inbox aria-hidden className="size-7" />
      </span>
      <h2 className="text-lg font-semibold">{title}</h2>
      {body && <p className="max-w-md text-secondary">{body}</p>}
      {children}
    </div>
  );
}

export function Table({
  caption,
  headers,
  rows,
}: {
  caption: string;
  headers: string[];
  rows: ReactNode[][];
}) {
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full border-collapse text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-canvas text-secondary">
          <tr>
            {headers.map((header) => (
              <th
                key={header}
                scope="col"
                className="whitespace-nowrap px-4 py-3 font-medium"
              >
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t border-border">
              {row.map((cell, j) => (
                <td key={j} className="px-4 py-3">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
