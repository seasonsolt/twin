import type { ComponentProps, ReactNode } from 'react';
import { cn } from '../../lib/utils';
import { Button, type ButtonProps, Textarea } from './controls';
import './chat.css';

/** Conversation surfaces keep their appearance in the kit, not in page markup. */
export function ChatSurface({
  variant,
  className,
  ...props
}: ComponentProps<'div'> & {
  variant: 'sheet' | 'panel' | 'stage' | 'composer' | 'empty';
}) {
  return (
    <div {...props} className={cn(`chat-surface-${variant}`, className)} />
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
