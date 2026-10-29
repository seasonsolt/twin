import { useId, useState } from 'react';
import { usePersonaEdition } from '../../stores/auth';
import { AnimatePresence, motion } from 'motion/react';
import {
  Badge,
  Button,
  Card,
  Field,
  Text,
  Textarea,
  toast,
} from '../../components/ui';
import { useMotionPreset } from '../../design/motion';
import {
  secondhand,
  TIER_LABELS,
  type ProfileItem,
  type ReviewStatus,
  type Tier,
} from './types';

/** The occasions behind a memory: when, where from, and what was said. */
export function EvidenceList({
  item,
  kindLabels,
}: {
  item: ProfileItem;
  kindLabels: Record<string, string>;
}) {
  return (
    <Text
      as="ul"
      size="sm"
      aria-label="条目证据"
      className="space-y-3 border-l-2 border-border pl-3"
    >
      {item.evidence.map((evidence, i) => (
        <li key={`${evidence.expression_id}-${i}`}>
          <Text size="xs" tone="tertiary">
            {[
              evidence.date,
              kindLabels[evidence.source_kind] ?? evidence.source_kind,
              evidence.own_words ? '原话' : '他人记述',
            ]
              .filter(Boolean)
              .join(' · ')}
          </Text>
          <blockquote className="whitespace-pre-wrap break-words">
            {evidence.quote}
          </blockquote>
        </li>
      ))}
    </Text>
  );
}

/** What the twin remembers, ready to use: the person corrects a wrong one or removes it, never confirms. */
export function ItemCard({
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
  /** Only the person behind the twin says who may use a memory; a private one is marked for everyone who can say. */
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
  const { reduced, transition, exit } = useMotionPreset('gentle');
  const send = (status: ReviewStatus) => {
    void onReview(item, status);
  };
  return (
    <Card
      as="article"
      padding="md"
      aria-label={item.statement}
      className="space-y-3"
    >
      {((!persona && item.tier === 'self') ||
        item.review === 'edited' ||
        secondhand(item)) && (
        <div className="flex flex-wrap gap-2">
          {!persona && item.tier === 'self' && (
            <Badge>{TIER_LABELS.self}</Badge>
          )}
          {item.review === 'edited' && <Badge tone="info">你改过</Badge>}
          {secondhand(item) && <Badge>只有别人说</Badge>}
        </div>
      )}
      <Text className="whitespace-pre-wrap break-words">{item.statement}</Text>
      {item.extracted_statement && (
        <Text size="sm" tone="secondary">
          原提炼：{item.extracted_statement}
        </Text>
      )}
      {item.applies_when && (
        <Text size="sm" tone="secondary">
          适用：{item.applies_when}
        </Text>
      )}
      {item.conflict && (
        <Text size="sm" tone="warning">
          矛盾：{item.conflict}
        </Text>
      )}
      <Button
        variant="ghost"
        size="sm"
        aria-expanded={open}
        aria-controls={`${id}-evidence`}
        onClick={() => setOpen(!open)}
      >
        依据 · {open ? '收起' : '展开'}
      </Button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={`${id}-evidence`}
            initial={reduced ? { opacity: 0 } : { opacity: 0, height: 0 }}
            animate={reduced ? { opacity: 1 } : { opacity: 1, height: 'auto' }}
            exit={
              reduced
                ? { opacity: 0, transition: exit }
                : { opacity: 0, height: 0 }
            }
            transition={transition}
            className="overflow-hidden"
          >
            <EvidenceList item={item} kindLabels={kindLabels} />
          </motion.div>
        )}
      </AnimatePresence>
      {editing ? (
        <form
          className="space-y-2"
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
          <div className="flex gap-2">
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
          </div>
        </form>
      ) : (
        <div className="flex flex-wrap gap-2" aria-label="修改这条记忆">
          <Button
            size="sm"
            variant="secondary"
            disabled={pending}
            onClick={() => {
              setDraft(item.statement);
              setEditing(true);
            }}
          >
            改一下
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-danger"
            disabled={pending}
            onClick={() => send('rejected')}
          >
            删掉
          </Button>
          {onTier && (
            <Button
              size="sm"
              variant="ghost"
              disabled={pending}
              onClick={() =>
                void onTier(item, item.tier === 'self' ? 'colleague' : 'self')
              }
            >
              {item.tier === 'self' ? '设为同事能用' : '设为只有本人'}
            </Button>
          )}
          {onTier && item.tier_changed && (
            <Button
              size="sm"
              variant="ghost"
              disabled={pending}
              onClick={() => void onTier(item, null)}
            >
              恢复默认
            </Button>
          )}
          {item.review === 'edited' && (
            <Button
              size="sm"
              variant="ghost"
              disabled={pending}
              onClick={() => send('unreviewed')}
            >
              恢复原样
            </Button>
          )}
        </div>
      )}
    </Card>
  );
}
