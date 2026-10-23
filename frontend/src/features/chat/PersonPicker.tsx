import { ChevronDown } from 'lucide-react';
import {
  PersonaPortrait,
  PersonaSwitcher,
} from '../../components/layout/PersonaSwitcher';
import { ChatIdentity, Text } from '../../components/ui';
import type { Persona } from '../../stores/personas';

/**
 * Whom the conversation is with, and where to change it: the one place the twin is picked in a conversation (beside
 * the box a message is written in, with ``inline``), and the person on the commitments page. ``compact`` is the
 * portrait alone, for a place with little room.
 */
export function PersonPicker({
  persona,
  name,
  compact = false,
  inline = false,
}: {
  persona?: Persona;
  name: string;
  /** The portrait alone, for a header with little room. */
  compact?: boolean;
  /** Part of a line of controls (the composer's), not a field of its own. */
  inline?: boolean;
}) {
  return (
    <PersonaSwitcher
      label={`切换分身（当前：${name}）`}
      className={
        compact
          ? 'flex shrink-0 items-center'
          : inline
            ? 'flex min-h-11 max-w-44 min-w-0 shrink items-center gap-2 py-1 pr-3 pl-1 text-left hover:bg-soft'
            : 'flex min-h-12 w-full min-w-0 items-center gap-2 border border-border bg-surface py-1 pr-3 pl-2 text-left hover:bg-soft'
      }
      trigger={
        <>
          <ChatIdentity size={compact ? 'mobile' : 'sheet'}>
            <PersonaPortrait persona={persona} />
          </ChatIdentity>
          {!compact && (
            <>
              <Text as="span" weight="medium" truncate className="flex-1">
                {name}
              </Text>
              <ChevronDown size={16} aria-hidden />
            </>
          )}
        </>
      }
    />
  );
}
