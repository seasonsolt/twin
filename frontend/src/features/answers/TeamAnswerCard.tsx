import { useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Row,
  Stack,
  Text,
  TextLink,
} from '../../components/ui';
import { askedPath, type Asked } from './askOwner';
import { confirmedText, type TeamAnswerCard as Data } from './types';

/**
 * What a person confirmed once, shown as it is: the question it answers, the words, whose it is and the day. It
 * stands apart from what the twin says. Once the person has said something else since, it is dashed and says what
 * and when. The way on, when it is not enough, is to ask them (问某某本人). `onAsk` hands the asker's question to the
 * person in the asker's name, says where their reply will come, and rejects with why it could not.
 */
export function TeamAnswerCard({
  card,
  onAsk,
}: {
  card: Data;
  onAsk?: () => Promise<Asked | void>;
}) {
  const [state, setState] = useState<'idle' | 'asking' | 'asked'>('idle');
  const [where, setWhere] = useState('');
  const [error, setError] = useState('');
  const stale = card.status === 'stale';
  const ask = () => {
    if (!onAsk || state !== 'idle') return;
    setState('asking');
    setError('');
    onAsk().then(
      (asked) => {
        setWhere(asked?.conversation_id ? askedPath(asked) : '');
        setState('asked');
      },
      (failure: unknown) => {
        setError(failure instanceof Error ? failure.message : '没能转出去');
        setState('idle');
      },
    );
  };
  return (
    <Card
      variant={stale ? 'dashed' : 'outline'}
      padding="md"
      as="article"
      aria-label="团队答案"
    >
      <Stack gap={2}>
        <Row gap={2} wrap>
          <Badge tone="info">团队答案</Badge>
          {stale && <Badge tone="warning">可能过期</Badge>}
          <Text as="span" size="xs" tone="secondary">
            {confirmedText(card)}
          </Text>
        </Row>
        <Text weight="bold" tone={stale ? 'secondary' : 'primary'}>
          {card.partial ? `只回答了：${card.title}` : card.title}
        </Text>
        <Text tone={stale ? 'secondary' : 'primary'}>{card.body}</Text>
        {stale && card.stale_note && (
          <Text size="xs" tone="secondary">
            {card.stale_note}
          </Text>
        )}
        {error && (
          <Text role="alert" size="xs" tone="danger">
            {error}
          </Text>
        )}
        {onAsk &&
          (state === 'asked' ? (
            <Row gap={2} wrap>
              <Text role="status" size="xs" tone="secondary">
                已转给{card.owner_name}本人 · 等回复
              </Text>
              {where && (
                <TextLink to={where} size="xs">
                  去看 ›
                </TextLink>
              )}
            </Row>
          ) : (
            <Row>
              <Button
                size="sm"
                variant={stale ? 'primary' : 'secondary'}
                loading={state === 'asking'}
                onClick={ask}
              >
                问{card.owner_name}本人
              </Button>
            </Row>
          ))}
      </Stack>
    </Card>
  );
}
