import { render } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { PersonFace } from '../features/library/PersonFace';
import type { Persona } from '../stores/personas';

afterEach(() => window.history.replaceState(null, '', '/'));

it('shows a twin’s photo through the path prefix the page is served under', () => {
  window.history.replaceState(null, '', '/twin/#/team');
  const twin: Persona = {
    id: 'p-ai',
    name: '艾总',
    avatar_url: '/api/media/avatar-image?persona=p-ai',
    sources: 1,
    created_at: 'x',
    is_default: false,
  };
  const { container } = render(<PersonFace name="艾总" twin={twin} />);
  expect(container.querySelector('img')?.getAttribute('src')).toBe(
    '/twin/api/media/avatar-image?persona=p-ai',
  );
});
