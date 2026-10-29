import { render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { TooltipProvider } from '../components/ui';
import { NoteCard } from '../features/chat/NoteCard';
import { useAuth, type Edition } from '../stores/auth';

afterEach(() => useAuth.setState({ identity: null }));

function signIn(edition?: Edition) {
  useAuth.setState({
    identity: { email: null, admin: true, auth_enabled: false, edition },
  });
}

function note() {
  render(
    <TooltipProvider>
      <NoteCard
        note={{ id: 's1', text: '周五前把方案发给小林', tier: 'self' }}
        onTier={() => Promise.resolve()}
      />
    </TooltipProvider>,
  );
  return screen.getByRole('radiogroup', { name: '谁能用这条记忆' });
}

it('keeps a note for the person or not at all in the persona edition, with no colleagues to open it to', () => {
  signIn('persona');
  const tiers = note();
  expect(tiers).toHaveTextContent('只有我');
  expect(tiers).toHaveTextContent('不存');
  expect(tiers).not.toHaveTextContent('同事能用');
});

it('offers colleagues a note on a server that names no edition, as the team edition does', () => {
  signIn();
  expect(note()).toHaveTextContent('同事能用');
});
