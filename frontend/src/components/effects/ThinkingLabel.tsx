import { useReducedMotion } from 'motion/react';
import ShinyText from '../reactbits/ShinyText';

export function ThinkingLabel({ text = '思考中…' }: { text?: string }) {
  const reduced = useReducedMotion();
  return (
    <span role="status" className="text-sm text-secondary">
      {reduced ? (
        text
      ) : (
        <ShinyText
          text={text}
          speed={3}
          delay={2}
          color="var(--text-secondary)"
          shineColor="var(--text-primary)"
        />
      )}
    </span>
  );
}
