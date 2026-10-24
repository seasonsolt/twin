import { useState } from 'react';
import { CircleHelp } from 'lucide-react';
import {
  Card,
  IconButton,
  Row,
  Segmented,
  Stack,
  Text,
  Tooltip,
} from '../../components/ui';
import type { NoteCard as Note, NoteTier } from './types';

const TIERS = [
  { id: 'colleague', label: '同事能用' },
  { id: 'self', label: '只有我' },
  { id: 'none', label: '不存' },
] as const satisfies readonly { id: NoteTier; label: string }[];

/**
 * What the assistant took down when the person said 记一下, and who may use it: it is kept for them alone until they
 * choose, 同事能用 lets colleagues' conversations draw on it, 不存 takes it back for good (the note is gone, so there is
 * no other choice after it). The choice is theirs and is made here, under the reply, where they see what was kept.
 */
export function NoteCard({
  note,
  onTier,
}: {
  note: Note;
  /** Rejects with why it could not be changed. */
  onTier(tier: NoteTier): Promise<void>;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const change = (tier: NoteTier) => {
    if (tier === note.tier || saving) return;
    setSaving(true);
    setError('');
    onTier(tier)
      .catch((failure: unknown) =>
        setError(failure instanceof Error ? failure.message : '没能改成功'),
      )
      .finally(() => setSaving(false));
  };
  return (
    <Card variant="soft" padding="sm" as="div" aria-label="记下的内容">
      <Stack gap={2}>
        <Text
          size="sm"
          tone={note.tier === 'none' ? 'tertiary' : 'primary'}
          className={note.tier === 'none' ? 'line-through' : undefined}
        >
          {note.text}
        </Text>
        {note.tier === 'none' ? (
          <Text size="xs" tone="tertiary">
            已不存
          </Text>
        ) : (
          <Row gap={2} wrap>
            <Segmented
              label="谁能用这条记忆"
              value={note.tier}
              options={TIERS}
              onChange={change}
              disabled={saving}
            />
            <Tooltip label="同事能用：同事问到相关的事，分身可以用它。只有我：只有你自己的对话能用。不存：删掉这条，不能再恢复。">
              <IconButton label="这几档是什么意思" shape="circle">
                <CircleHelp className="size-4" aria-hidden />
              </IconButton>
            </Tooltip>
          </Row>
        )}
        {error && (
          <Text role="alert" size="xs" tone="danger">
            {error}
          </Text>
        )}
      </Stack>
    </Card>
  );
}
