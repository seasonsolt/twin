import { useState, type ReactNode } from 'react';
import { motion, type HTMLMotionProps } from 'motion/react';
import { usePersonas } from '../../stores/personas';
import { useStatus } from '../../stores/status';
import { personaUrl } from '../../lib/persona';
import { cn } from '../../lib/utils';

export function StageHeader({
  variant = 'compact',
  name: suppliedName,
  intro,
  portrait,
  left,
  right,
  footer,
  children,
  className,
  ...props
}: Omit<HTMLMotionProps<'header'>, 'children'> & {
  variant?: 'compact' | 'expanded' | 'future' | 'brand' | 'chat';
  name?: string;
  intro?: ReactNode;
  portrait?: ReactNode;
  left?: ReactNode;
  right?: ReactNode;
  footer?: ReactNode;
  children?: ReactNode;
}) {
  const { id, items } = usePersonas();
  const current = items.find((item) => item.id === id);
  const targetName = useStatus((state) => state.data?.target_name);
  const brand = variant === 'brand';
  const name = brand
    ? 'twin'
    : (suppliedName ?? current?.name ?? targetName ?? '本人');
  const url =
    variant !== 'future' && current?.avatar_url
      ? personaUrl(current.avatar_url, current.id)
      : undefined;
  const [failed, setFailed] = useState<string>();
  return (
    <motion.header
      aria-label={brand ? 'twin 的舞台' : `${name}的舞台`}
      {...props}
      className={cn(
        'stage-header',
        variant === 'chat' ? 'chat-stage' : `stage-${variant}`,
        className,
      )}
    >
      <span aria-hidden className="stage-sun" />
      <span aria-hidden className="stage-coral" />
      <div className="stage-actions">
        <div>{left}</div>
        <div>{right}</div>
      </div>
      <div className="stage-person">
        {brand ? (
          <div className="stage-brand-mark" aria-hidden>
            <span />
            <span />
          </div>
        ) : (
          (portrait ?? (
            <div className="stage-circle stage-portrait">
              {url && failed !== url ? (
                <img
                  src={url}
                  alt={`${name}的肖像`}
                  onError={() => setFailed(url)}
                />
              ) : (
                <span
                  role="img"
                  aria-label={`${name}的头像`}
                  className="persona-name stage-initial"
                >
                  {Array.from(name.trim())[0] || '本'}
                </span>
              )}
            </div>
          ))
        )}
        <h1 className="persona-name stage-name">{name}</h1>
        {intro}
      </div>
      {(footer || variant === 'future') && (
        <div className="stage-footer">
          {footer ?? (
            <div
              className="future-steps"
              role="img"
              aria-label="第 1 步，共 4 步"
            >
              {[1, 2, 3, 4].map((step) => (
                <i key={step} data-current={step === 1} />
              ))}
            </div>
          )}
        </div>
      )}
      {children}
    </motion.header>
  );
}
