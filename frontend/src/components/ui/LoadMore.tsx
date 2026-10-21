import { useEffect, useRef, type ReactNode } from 'react';
import { Button } from './controls';
import { Row } from './layout';
import { Text } from './typography';

/** Continue a list near its end, with the same action available to keyboard users and older browsers. */
export function LoadMore({
  shown,
  total,
  onLoadMore,
  label = '继续加载',
  description,
  disabled = false,
  active = true,
}: {
  shown: number;
  total: number;
  onLoadMore: () => void;
  label?: string;
  description?: ReactNode;
  disabled?: boolean;
  active?: boolean;
}) {
  const button = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const target = button.current;
    if (
      !target ||
      !active ||
      disabled ||
      shown >= total ||
      typeof IntersectionObserver === 'undefined'
    )
      return;
    let observing = true;
    const observer = new IntersectionObserver(
      (entries) => {
        if (!observing || !entries.some((entry) => entry.isIntersecting))
          return;
        observing = false;
        observer.disconnect();
        onLoadMore();
      },
      { rootMargin: '0px 0px 160px 0px' },
    );
    observer.observe(target);
    return () => {
      observing = false;
      observer.disconnect();
    };
  }, [shown, total, active, disabled, onLoadMore]);

  if (shown >= total) return null;
  return (
    <Row gap={3} justify="between" wrap>
      <Text size="sm" tone="secondary" role="status">
        {description ?? `已显示 ${shown} / ${total}`}
      </Text>
      <Button
        ref={button}
        variant="ghost"
        size="sm"
        disabled={disabled}
        onClick={onLoadMore}
      >
        {label}
      </Button>
    </Row>
  );
}
