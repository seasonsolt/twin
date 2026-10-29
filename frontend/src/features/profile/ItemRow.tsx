import { useId, useState } from 'react';
import { usePersonaEdition } from '../../stores/auth';
import {
  ActionMenu,
  Badge,
  Button,
  Field,
  ListRow,
  Row,
  Stack,
  Text,
  Textarea,
  toast,
} from '../../components/ui';
import { EvidenceList } from './ItemCard';
import {
  secondhand,
  TIER_LABELS,
  type ProfileItem,
  type ReviewStatus,
  type Tier,
} from './types';

/**
 * What the twin remembers, as one line: the memory, when it applies and how many occasions it rests on. 改 opens
 * the field to correct it; the evidence, removing it, putting the extracted wording back and who may use it are
 * under “⋯”. Only the person behind the twin can say who may use a memory (``onTier``); a private one is marked.
 */
export function ItemRow({
  item,
  pending,
  onReview,
  onTier: chooseTier,
  kindLabels,
}: {
  item: ProfileItem;
  pending: boolean;
  onReview: (
    item: ProfileItem,
    status: ReviewStatus,
    statement?: string,
  ) => Promise<boolean>;
  onTier?: (item: ProfileItem, tier: Tier | null) => Promise<boolean>;
  kindLabels: Record<string, string>;
}) {
  // The persona edition has no colleagues: no memory is marked private, and none is opened to them.
  const persona = usePersonaEdition();
  const onTier = persona ? undefined : chooseTier;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(item.statement);
  const [open, setOpen] = useState(false);
  const id = useId();
  const occasions = new Set(item.evidence.map((e) => e.source_id)).size;
  const edit = () => {
    setDraft(item.statement);
    setEditing(true);
  };
  return (
    <ListRow
      as="article"
      variant="divided"
      aria-label={item.statement}
      title={
        <Text weight="regular" className="whitespace-pre-wrap break-words">
          {item.statement}
        </Text>
      }
      meta={
        <Row gap={2} wrap>
          <Text as="span" size="sm" tone="secondary">
            {[item.applies_when, occasions > 0 ? `${occasions} 处依据` : '']
              .filter(Boolean)
              .join(' · ')}
          </Text>
          {!persona && item.tier === 'self' && (
            <Badge>{TIER_LABELS.self}</Badge>
          )}
          {item.review === 'edited' && <Badge tone="info">你改过</Badge>}
          {secondhand(item) && <Badge>只有别人说</Badge>}
          {item.conflict && <Badge tone="warning">有矛盾</Badge>}
        </Row>
      }
      trailing={
        !editing && (
          <>
            <Button
              size="sm"
              variant="secondary"
              disabled={pending}
              aria-label={`改这条：${item.statement}`}
              onClick={edit}
            >
              改一下
            </Button>
            <ActionMenu
              label={`更多：${item.statement}`}
              items={[
                {
                  label: open ? '收起依据' : '依据',
                  onSelect: () => setOpen(!open),
                },
                {
                  label: '删掉',
                  danger: true,
                  disabled: pending,
                  onSelect: () => void onReview(item, 'rejected'),
                },
                ...(onTier
                  ? [
                      {
                        label:
                          item.tier === 'self'
                            ? '设为同事能用'
                            : '设为只有本人',
                        disabled: pending,
                        onSelect: () =>
                          void onTier(
                            item,
                            item.tier === 'self' ? 'colleague' : 'self',
                          ),
                      },
                    ]
                  : []),
                ...(onTier && item.tier_changed
                  ? [
                      {
                        label: '恢复默认',
                        disabled: pending,
                        onSelect: () => void onTier(item, null),
                      },
                    ]
                  : []),
                ...(item.review === 'edited'
                  ? [
                      {
                        label: '恢复原样',
                        disabled: pending,
                        onSelect: () => void onReview(item, 'unreviewed'),
                      },
                    ]
                  : []),
              ]}
            />
          </>
        )
      }
    >
      {open && (
        <Stack gap={2}>
          {item.extracted_statement && (
            <Text size="sm" tone="secondary">
              原提炼：{item.extracted_statement}
            </Text>
          )}
          {item.conflict && (
            <Text size="sm" tone="warning">
              矛盾：{item.conflict}
            </Text>
          )}
          <EvidenceList item={item} kindLabels={kindLabels} />
        </Stack>
      )}
      {editing && (
        <Stack
          as="form"
          gap={2}
          onSubmit={(event) => {
            event.preventDefault();
            const text = draft.trim();
            if (!text) {
              toast('表述不能为空', 'warning');
              return;
            }
            void onReview(item, 'edited', text).then((ok) => {
              if (ok) setEditing(false);
            });
          }}
        >
          <Field id={`${id}-statement`} label="修改表述">
            <Textarea
              id={`${id}-statement`}
              value={draft}
              maxLength={1000}
              autoFocus
              disabled={pending}
              onChange={(event) => setDraft(event.target.value)}
            />
          </Field>
          <Row gap={2}>
            <Button type="submit" size="sm" loading={pending}>
              保存修改
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={pending}
              onClick={() => setEditing(false)}
            >
              取消
            </Button>
          </Row>
        </Stack>
      )}
    </ListRow>
  );
}
