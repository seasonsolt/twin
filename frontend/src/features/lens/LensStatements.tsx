import { Disclosure, Stack, Text } from '../../components/ui';
import type { LensStatement } from './types';

/** "10 月 22 日" from an ISO day. */
function dayOf(iso: string | null): string {
  const match = iso ? /^\d{4}-(\d{2})-(\d{2})/.exec(iso) : null;
  return match ? `${Number(match[1])} 月 ${Number(match[2])} 日` : '';
}

/** What a lens says, one statement to a block, each with the words it stands on folded under 依据. */
export function LensStatements({ views }: { views: LensStatement[] }) {
  return (
    <Stack as="ul" gap={3}>
      {views.map((view) => (
        <li key={`${view.facet_id}-${view.text}`}>
          <Stack gap={1}>
            <Text>{view.text}</Text>
            <Text size="xs" tone="secondary">
              {view.facet}
            </Text>
            {view.basis.length > 0 && (
              <Disclosure variant="plain" summary="依据">
                <Stack as="ul" gap={2}>
                  {view.basis.map((basis) => (
                    <li key={`${basis.date}-${basis.quote}`}>
                      <Text size="sm" tone="secondary">
                        “{basis.quote}”
                      </Text>
                      <Text size="xs" tone="tertiary">
                        {[dayOf(basis.date), basis.kind]
                          .filter(Boolean)
                          .join(' · ')}
                      </Text>
                    </li>
                  ))}
                </Stack>
              </Disclosure>
            )}
          </Stack>
        </li>
      ))}
    </Stack>
  );
}
