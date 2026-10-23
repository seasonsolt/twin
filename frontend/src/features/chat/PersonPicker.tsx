import { ChevronDown } from 'lucide-react';
import {
  PersonaPortrait,
  PersonaSwitcher,
} from '../../components/layout/PersonaSwitcher';
import { ChatIdentity, Text } from '../../components/ui';
import type { Persona } from '../../stores/personas';

/**
 * Whom the conversation is with, and where to change it: the one place the twin is picked in a conversation (the
 * list's top, and the portrait alone where the list is folded away or on a phone).
 */
export function PersonPicker({
  persona,
  name,
  compact = false,
}: {
  persona?: Persona;
  name: string;
  /** The portrait alone, for a header with little room. */
  compact?: boolean;
}) {
  return (
    <PersonaSwitcher
      label={`切换分身（当前：${name}）`}
      className={
        compact
          ? 'flex shrink-0 items-center'
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
