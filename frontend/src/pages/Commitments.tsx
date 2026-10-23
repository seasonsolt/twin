import { Page } from '../components/ui';
import { PersonPicker } from '../features/chat/PersonPicker';
import { usePersonaId } from '../lib/usePersonaState';
import { usePersonas } from '../stores/personas';
import { Ledger } from './Ledger';

/** The commitments of one person's twin: choose whose, and the ledger is theirs. The member page holds the same
 * ledger for the twin it is about. */
export function Commitments() {
  const id = usePersonaId();
  const persona = usePersonas((state) => state.items.find((p) => p.id === id));
  return (
    <Page
      title="承诺"
      titleSize="display"
      actions={
        <PersonPicker persona={persona} name={persona?.name ?? '选人'} />
      }
    >
      <Ledger />
    </Page>
  );
}
