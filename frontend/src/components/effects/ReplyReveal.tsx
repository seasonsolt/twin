import { motion } from 'motion/react';
import { useMotionPreset } from '../../design/motion';
import { cn } from '../../lib/utils';

export function segmentReply(text: string): string[] {
  const Segmenter = (
    Intl as typeof Intl & {
      Segmenter?: new (
        locale?: string,
        options?: { granularity: 'word' },
      ) => { segment: (text: string) => Iterable<{ segment: string }> };
    }
  ).Segmenter;
  if (Segmenter)
    return Array.from(
      new Segmenter(undefined, { granularity: 'word' }).segment(text),
      (unit) => unit.segment,
    );
  return (
    text.match(
      /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]|\s+|[^\s\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]+/gu,
    ) ?? []
  );
}

export function replyUnitDelay(count: number) {
  return Math.min(0.025, 1.08 / Math.max(1, count - 1));
}

export function ReplyReveal({
  text,
  className,
}: {
  text: string;
  className?: string;
}) {
  const { reduced } = useMotionPreset();
  const units = segmentReply(text);
  // BlurText's space splitter cannot preserve Chinese word boundaries. Keep its
  // subtle reveal here without modifying vendored code or inserting fake spaces.
  return (
    <div className={cn('whitespace-pre-wrap text-primary', className)}>
      <span className="sr-only">{text}</span>
      <div aria-hidden="true">
        {reduced ? (
          <p>{text}</p>
        ) : (
          <p className="blur-text">
            {units.map((unit, index) => (
              <motion.span
                key={index}
                data-reveal-unit=""
                className="inline-block whitespace-pre-wrap"
                initial={{ filter: 'blur(3px)', opacity: 0, y: 2 }}
                animate={{ filter: 'blur(0px)', opacity: 1, y: 0 }}
                transition={{
                  duration: 0.12,
                  delay: index * replyUnitDelay(units.length),
                }}
              >
                {unit}
              </motion.span>
            ))}
          </p>
        )}
      </div>
    </div>
  );
}
