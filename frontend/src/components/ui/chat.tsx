import type { ComponentProps, CSSProperties, ReactNode } from 'react';
import { cn } from '../../lib/utils';
import { Button, type ButtonProps, Textarea } from './controls';
import './chat.css';

/** Conversation surfaces keep their appearance in the kit, not in page markup. */
export function ChatSurface({
  variant,
  width,
  className,
  ...props
}: Omit<ComponentProps<'div'>, 'style'> & {
  variant: 'sheet' | 'panel' | 'stage' | 'composer' | 'empty';
  /** The sheet's width in CSS pixels, when the viewer has set one; otherwise --spacing-chat-sheet. */
  width?: number;
}) {
  return (
    <div
      {...props}
      style={
        width === undefined
          ? undefined
          : ({ '--chat-sheet-width': `${width}px` } as CSSProperties)
      }
      className={cn(`chat-surface-${variant}`, className)}
    />
  );
}
export function ChatMessage({
  speaker,
  last = false,
  ...props
}: ComponentProps<'article'> & {
  speaker: 'user' | 'twin';
  last?: boolean;
}) {
  return (
    <article
      {...props}
      data-speaker={speaker}
      data-last-answer={last || undefined}
      className="chat-message min-w-0"
    />
  );
}
export function ChatAction({
  selected = false,
  variant = 'quiet',
  ...props
}: Omit<ButtonProps, 'variant'> & {
  selected?: boolean;
  variant?: 'quiet' | 'send' | 'row';
}) {
  return (
    <Button
      {...props}
      variant="ghost"
      className={cn(
        `chat-action-${variant}`,
        selected && 'chat-action-selected',
        props.className,
      )}
    />
  );
}
export function ChatInput(props: ComponentProps<typeof Textarea>) {
  return <Textarea {...props} rows={2} className="chat-input" />;
}
export function ChatIdentity({
  children,
  size = 'sheet',
}: {
  children: ReactNode;
  size?: 'sheet' | 'mobile' | 'empty';
}) {
  return (
    <span className={`chat-identity chat-identity-${size}`}>{children}</span>
  );
}
