import { Segmented } from '../../components/ui';

/** Who may use a reply as a memory: the choice made when it is sent. */
export type ReplyTier = 'colleague' | 'self' | 'none';

const KEPT = [
  { id: 'colleague', label: '按默认' },
  { id: 'self', label: '只有我' },
] as const satisfies readonly { id: ReplyTier; label: string }[];
const ALL = [...KEPT, { id: 'none', label: '不存' }] as const;

/**
 * The tier a reply is kept in when the person sends it: 按默认 (the default: as its facet is, which a colleague may use
 * unless it is a private one such as the family's), 只有我, or 不存, which only writes it into the asker's conversation. A reply with nothing to be written into (the old questions) is always kept, so it has
 * no 不存.
 */
export function ReplyTierChoice({
  value,
  onChange,
  disabled,
  keepable = false,
}: {
  value: ReplyTier;
  onChange: (tier: ReplyTier) => void;
  disabled?: boolean;
  /** Offer only the two ways of keeping it. */
  keepable?: boolean;
}) {
  return (
    <Segmented
      label="谁能用这条记忆"
      value={value}
      options={keepable ? KEPT : ALL}
      onChange={onChange}
      disabled={disabled}
    />
  );
}
