import { useState } from 'react';
import { Badge, Button, Card, Row, Stack, Text } from '../../components/ui';
import { LensStatements } from './LensStatements';
import type { LensCardData } from './types';

/**
 * A lens's answer under a colleague's question: statements with the words they stand on, said to be inferred from what
 * the person said and not their opinion. Where it has nothing to say, or the matter is the person's to settle, it says
 * so and offers 问某某本人: `onAskOwner` hands the question to the person in the asker's name, as a request of its
 * own, and rejects with why it could not. It is given only while nothing has been handed over; where the question
 * stands afterwards is the line under the answer.
 */
export function LensCard({
  card,
  onAskOwner,
}: {
  card: LensCardData;
  onAskOwner?: () => Promise<void>;
}) {
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState('');
  const ask = () => {
    if (!onAskOwner || asking) return;
    setAsking(true);
    setError('');
    onAskOwner().then(
      () => setAsking(false),
      (failure: unknown) => {
        setError(failure instanceof Error ? failure.message : '没能转出去');
        setAsking(false);
      },
    );
  };
  const owner = card.owner_name;
  return (
    <Card variant="outline" padding="md" as="article" aria-label="赋能">
      <Stack gap={3}>
        <Row gap={2} wrap>
          <Badge tone="info">赋能</Badge>
          <Text as="span" size="xs" tone="secondary">
            {owner} · {card.name}
          </Text>
        </Row>
        {card.empty ? (
          <Text tone="secondary">没有能回答的内容。</Text>
        ) : (
          <LensStatements views={card.views} />
        )}
        {(card.empty || card.settled_by_person) && (
          <Text size="sm" tone="secondary">
            {card.empty
              ? `可直接问${owner}。`
              : `具体怎么定：未开放，可直接问${owner}。`}
          </Text>
        )}
        {error && (
          <Text role="alert" size="xs" tone="danger">
            {error}
          </Text>
        )}
        {onAskOwner && (card.empty || card.settled_by_person) && (
          <Row>
            <Button
              size="sm"
              variant="secondary"
              loading={asking}
              onClick={ask}
            >
              问{owner}本人
            </Button>
          </Row>
        )}
        <Text size="xs" tone="tertiary">
          {card.note}
        </Text>
      </Stack>
    </Card>
  );
}
