import { useId, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Badge, Button, Field, Textarea, toast } from '../../components/ui';
import type { Tone } from '../../components/ui/controls';
import { useMotionPreset } from '../../design/motion';
import { reviewLabels, type ProfileItem, type ReviewStatus } from './types';

const reviewTones: Record<ReviewStatus, Tone> = {
  unreviewed: 'neutral',
  confirmed: 'success',
  edited: 'info',
  rejected: 'danger',
};
export function ItemCard({
  item,
  pending,
  onReview,
  kindLabels,
}: {
  item: ProfileItem;
  pending: boolean;
  onReview: (
    item: ProfileItem,
    status: ReviewStatus,
    statement?: string,
  ) => Promise<boolean>;
  kindLabels: Record<string, string>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(item.statement);
  const [open, setOpen] = useState(false);
  const id = useId();
  const { reduced, transition, exit } = useMotionPreset('gentle');
  const send = (status: ReviewStatus) => {
    void onReview(item, status);
  };
  return (
    <article
      aria-label={`档案条目 ${item.item_id}`}
      className="space-y-3 rounded-md border border-border bg-surface p-4"
    >
      <div className="flex flex-wrap gap-2">
        <Badge tone={reviewTones[item.review]}>
          {reviewLabels[item.review]}
        </Badge>
        <Badge tone="info">{item.facet_name}</Badge>
      </div>
      <p className="whitespace-pre-wrap break-words">{item.statement}</p>
      {item.extracted_statement && (
        <p className="text-sm text-secondary">
          原提炼：{item.extracted_statement}
        </p>
      )}
      {item.applies_when && (
        <p className="text-sm text-secondary">适用：{item.applies_when}</p>
      )}
      {item.conflict && (
        <p className="text-sm text-warning">矛盾：{item.conflict}</p>
      )}
      <Button
        variant="ghost"
        size="sm"
        aria-expanded={open}
        aria-controls={`${id}-evidence`}
        onClick={() => setOpen(!open)}
      >
        证据 {item.occasions} 处 · {open ? '收起' : '展开'}
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
            <ul
              aria-label="条目证据"
              className="space-y-3 border-l-2 border-border pl-3 text-sm"
            >
              {item.evidence.map((evidence, i) => (
                <li key={`${evidence.expression_id}-${i}`}>
                  <p className="text-xs text-tertiary">
                    {[
                      evidence.date,
                      kindLabels[evidence.source_kind] ?? evidence.source_kind,
                      evidence.own_words ? '原话' : '他人记述',
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </p>
                  <blockquote className="whitespace-pre-wrap break-words">
                    {evidence.quote}
                  </blockquote>
                </li>
              ))}
            </ul>
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
        <div className="flex flex-wrap gap-2" aria-label="条目审核操作">
          {item.review === 'unreviewed' ? (
            <>
              <Button
                size="sm"
                disabled={pending}
                onClick={() => send('confirmed')}
              >
                确认
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={pending}
                onClick={() => {
                  setDraft(item.statement);
                  setEditing(true);
                }}
              >
                修改
              </Button>
              <Button
                size="sm"
                variant="danger"
                disabled={pending}
                onClick={() => send('rejected')}
              >
                驳回
              </Button>
            </>
          ) : (
            <>
              <Button
                size="sm"
                variant="secondary"
                disabled={pending}
                onClick={() => send('unreviewed')}
              >
                撤销审核
              </Button>
              {item.review !== 'rejected' && (
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={pending}
                  onClick={() => {
                    setDraft(item.statement);
                    setEditing(true);
                  }}
                >
                  修改
                </Button>
              )}
            </>
          )}
        </div>
      )}
    </article>
  );
}
