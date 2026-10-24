import { useState } from 'react';
import { api } from '../../lib/api';
import {
  ActionMenu,
  Button,
  ListRow,
  Row,
  Stack,
  Text,
  Textarea,
  toast,
} from '../../components/ui';
import type { AnsweredQuestion } from './useAway';

/**
 * An answer the twin guessed for a colleague, who was told it was a guess. 没错 puts it away; “⋯ → 更正” opens the
 * box for what is right, which goes into the colleague's conversation as the person's own and is remembered.
 */
export function Guessed({
  item,
  onDone,
}: {
  item: AnsweredQuestion;
  onDone: () => Promise<void>;
}) {
  const [correcting, setCorrecting] = useState(false);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const base = `/api/persona/answers/${encodeURIComponent(item.conversation_id)}/${item.turn}`;
  const run = async (action: string, json: object, done: string) => {
    setBusy(true);
    setError('');
    try {
      await api(`${base}/${action}`, { method: 'POST', json });
      toast(done, 'success');
      await onDone();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '保存失败');
    } finally {
      setBusy(false);
    }
  };
  return (
    <ListRow
      variant="divided"
      title={
        <Stack gap={0}>
          <Text weight="regular" twoLines={!correcting}>
            <Text as="span" tone="secondary">
              {item.asker_name}问：
            </Text>
            {item.question}
          </Text>
          <Text
            weight="regular"
            twoLines={!correcting}
            title={`${item.asker_name}问：${item.question}\n分身答：${item.answer}`}
          >
            <Text as="span" tone="secondary">
              分身答：
            </Text>
            {item.answer}
          </Text>
        </Stack>
      }
      trailing={
        !correcting && (
          <>
            <Button
              size="sm"
              variant="secondary"
              loading={busy}
              onClick={() => void run('confirm', {}, '已记下')}
            >
              没错
            </Button>
            <ActionMenu
              label={`更多：${item.question}`}
              items={[
                {
                  label: '更正',
                  disabled: busy,
                  onSelect: () => setCorrecting(true),
                },
              ]}
            />
          </>
        )
      }
    >
      {correcting && (
        <Stack gap={2}>
          <label
            htmlFor={`correct-${item.conversation_id}-${item.turn}`}
            className="sr-only"
          >
            正确的说法
          </label>
          <Textarea
            id={`correct-${item.conversation_id}-${item.turn}`}
            autoFocus
            value={text}
            placeholder={`告诉${item.asker_name}正确的说法，也会记进你的记忆`}
            onChange={(event) => setText(event.target.value)}
          />
          {error && (
            <Text role="alert" size="sm" tone="danger">
              {error}
            </Text>
          )}
          <Row gap={2} justify="end">
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => setCorrecting(false)}
            >
              取消
            </Button>
            <Button
              size="sm"
              loading={busy}
              disabled={!text.trim()}
              onClick={() =>
                void run('correct', { text: text.trim() }, '已更正')
              }
            >
              发送更正
            </Button>
          </Row>
        </Stack>
      )}
      {!correcting && error && (
        <Text role="alert" size="sm" tone="danger">
          {error}
        </Text>
      )}
    </ListRow>
  );
}
