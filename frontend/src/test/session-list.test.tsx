import { render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { TooltipProvider } from '../components/ui';
import { SessionList, type Session } from '../features/chat/SessionList';
import { usePersonas, type Persona } from '../stores/personas';

const twin = (
  id: string,
  name: string,
  avatar_url: string | null,
): Persona => ({
  id,
  name,
  avatar_url,
  sources: 1,
  created_at: '2025-01-01T00:00:00Z',
  is_default: false,
});

beforeEach(() => {
  usePersonas.setState({
    items: [twin('t_li', '李总', '/api/personas/t_li/avatar')],
  });
});

const list = (sessions: Session[]) =>
  render(
    <TooltipProvider>
      <SessionList
        open
        inline
        onOpenChange={vi.fn()}
        sessions={sessions}
        current={null}
        onOpen={vi.fn(() => true)}
        onNew={vi.fn()}
        onDelete={vi.fn(async () => {})}
        name="张总"
      />
    </TooltipProvider>,
  );

const row = (title: string) =>
  screen.getByText(title).closest('button') as HTMLElement;

it('leads a row with the face of whom it is with, where the list spans people', () => {
  list([
    {
      kind: 'chat',
      id: 'c1',
      title: '预算怎么排',
      updated_at: new Date().toISOString(),
      who: '李总',
      personaId: 't_li',
    },
    {
      kind: 'chat',
      id: 'c2',
      title: '周会安排',
      updated_at: new Date().toISOString(),
      who: '王总',
      personaId: 't_wang',
    },
    {
      kind: 'chat',
      id: 'c3',
      title: '自己的事',
      updated_at: new Date().toISOString(),
      personaId: 't_li',
    },
  ]);
  // A listed twin shows its portrait, one not listed yet the first character of the name.
  expect(row('预算怎么排').querySelector('img')).toHaveAttribute(
    'src',
    '/api/personas/t_li/avatar',
  );
  expect(row('周会安排').firstElementChild).toHaveTextContent('王');
  // A list of one person's conversations needs no face on every row.
  expect(row('自己的事').querySelector('[aria-hidden="true"]')).toBeNull();
});
