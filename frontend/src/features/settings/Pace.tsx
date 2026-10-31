import { useEffect, useState } from 'react';
import { Input, Row, Section, Select, Text } from '../../components/ui';
import { api } from '../../lib/api';

export type PaceKind = 'off' | 'daily_minutes' | 'weekly_times';
export interface PaceState {
  pace: { kind: PaceKind; limit: number };
  used: { minutes_today: number; times_week: number } | null;
  /** The line to show above the conversation now, or null. */
  reminder: string | null;
}

const KINDS: { id: PaceKind; label: string; unit: string }[] = [
  { id: 'off', label: '关闭', unit: '' },
  { id: 'daily_minutes', label: '每天最多', unit: '分钟' },
  { id: 'weekly_times', label: '每周最多', unit: '次' },
];

/** 节奏提醒 (P3.6): the pace the person sets for talking with their twin; off unless they turn it on. */
export function Pace() {
  const [state, setState] = useState<PaceState | null>(null);
  const [limit, setLimit] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    void api<PaceState>('/api/persona/pace', { signal: controller.signal })
      .then((next) => {
        setState(next);
        setLimit(String(next.pace.limit));
      })
      .catch(() => {
        if (!controller.signal.aborted) setError('读不到节奏设置');
      });
    return () => controller.abort();
  }, []);
  const save = (kind: PaceKind, value: number) => {
    setError('');
    void api<PaceState>('/api/persona/pace', {
      method: 'PUT',
      json: { kind, limit: value },
    })
      .then((next) => {
        setState(next);
        setLimit(String(next.pace.limit));
      })
      .catch(() => setError('没能保存，请重试'));
  };
  if (!state)
    return error ? (
      <Text role="alert" size="sm" tone="danger">
        {error}
      </Text>
    ) : null;
  const kind = state.pace.kind;
  const unit = KINDS.find((k) => k.id === kind)?.unit ?? '';
  return (
    <Section level={4} title="节奏提醒">
      <Row gap={2} wrap>
        <Select
          aria-label="节奏"
          value={kind}
          onChange={(event) =>
            save(event.target.value as PaceKind, state.pace.limit)
          }
        >
          {KINDS.map((k) => (
            <option key={k.id} value={k.id}>
              {k.label}
            </option>
          ))}
        </Select>
        {kind !== 'off' && (
          <>
            <Input
              aria-label={unit === '次' ? '每周次数' : '每天分钟'}
              type="number"
              inputMode="numeric"
              min={1}
              max={1440}
              width="name"
              value={limit}
              onChange={(event) => setLimit(event.target.value)}
              onBlur={() => {
                const value = Number(limit);
                if (Number.isInteger(value) && value >= 1 && value <= 1440) {
                  if (value !== state.pace.limit) save(kind, value);
                } else setLimit(String(state.pace.limit));
              }}
            />
            <Text>{unit}</Text>
          </>
        )}
      </Row>
      {error && (
        <Text role="alert" size="sm" tone="danger">
          {error}
        </Text>
      )}
    </Section>
  );
}
