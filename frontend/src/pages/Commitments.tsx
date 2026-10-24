import { useSearchParams } from 'react-router';
import { Chip, EmptyState, Page, Row } from '../components/ui';
import { useNoTwin } from '../components/layout/shellContext';
import { PersonPicker } from '../features/chat/PersonPicker';
import { usePersonaId } from '../lib/usePersonaState';
import { usePersonas } from '../stores/personas';
import { Ledger } from './Ledger';

/** The commitments of one person's twin: choose whose, and the ledger is theirs; or all of them together, a meeting
 * several people were in counted once. The member page holds the same ledger for the twin it is about. */
export function Commitments() {
  const id = usePersonaId();
  const persona = usePersonas((state) => state.items.find((p) => p.id === id));
  const [params, setParams] = useSearchParams();
  const everyone = params.get('who') === 'all';
  const noTwin = useNoTwin();
  const switchTo = usePersonas((state) => state.switchTo);
  if (noTwin)
    return (
      <Page title="承诺" titleSize="display">
        <EmptyState title="还没有承诺" />
      </Page>
    );
  return (
    <Page
      title="承诺"
      titleSize="display"
      actions={
        <Row gap={2}>
          <div className="shrink-0">
            <Chip
              pressed={everyone}
              onClick={() => setParams(everyone ? {} : { who: 'all' })}
            >
              全部
            </Chip>
          </div>
          {!everyone && (
            <PersonPicker
              managed
              persona={persona}
              name={persona?.name ?? '选人'}
            />
          )}
        </Row>
      }
    >
      <Ledger
        key={everyone ? 'all' : id}
        everyone={everyone}
        onOpen={(twinId) => {
          // Leave the list once the twin is in view, so the one left is not read in between.
          void switchTo(twinId).then(() => setParams({}));
        }}
      />
    </Page>
  );
}
