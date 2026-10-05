import { useReducedMotion } from 'motion/react';
import CountUp from '../reactbits/CountUp';

export function MetricNumber({
  value,
  from = 0,
  suffix = '',
}: {
  value: number;
  from?: number;
  suffix?: string;
}) {
  const reduced = useReducedMotion();
  const format = (number: number) =>
    new Intl.NumberFormat('en-US', { maximumFractionDigits: 10 }).format(
      number,
    );
  const final = format(value);
  return (
    <span className="inline-grid text-primary tabular-nums">
      <span className="sr-only">
        {final}
        {suffix}
      </span>
      <span aria-hidden="true" className="invisible col-start-1 row-start-1">
        {final}
        {suffix}
      </span>
      <span aria-hidden="true" className="invisible col-start-1 row-start-1">
        {format(from)}
        {suffix}
      </span>
      <span aria-hidden="true" className="col-start-1 row-start-1">
        {reduced ? (
          final
        ) : (
          <CountUp
            key={`${from}:${value}`}
            from={from}
            to={value}
            duration={0.6}
            separator=","
          />
        )}
        {suffix}
      </span>
    </span>
  );
}
