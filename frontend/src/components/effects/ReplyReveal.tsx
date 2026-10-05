import { useReducedMotion } from 'motion/react';
import BlurText from '../reactbits/BlurText';
import { cn } from '../../lib/utils';

export function ReplyReveal({
  text,
  className,
}: {
  text: string;
  className?: string;
}) {
  const reduced = useReducedMotion();
  return (
    <div className={cn('text-primary', className)}>
      <span className="sr-only">{text}</span>
      <div aria-hidden="true">
        {reduced ? (
          <p>{text}</p>
        ) : (
          <BlurText
            key={text}
            text={text}
            animateBy="words"
            delay={Math.min(25, 150 / Math.max(1, text.split(' ').length))}
            stepDuration={0.12}
            animationFrom={{ filter: 'blur(3px)', opacity: 0, y: 2 }}
            animationTo={[{ filter: 'blur(0px)', opacity: 1, y: 0 }]}
          />
        )}
      </div>
    </div>
  );
}
