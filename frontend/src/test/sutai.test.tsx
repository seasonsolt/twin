import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { expect, it, vi } from 'vitest';
import { TwinCore } from '../components/effects';
import { CitationChip, GlassPanel, PillNav, RiseText } from '../components/ui';

it('marks the place you are in on the pill and links the others', () => {
  render(
    <MemoryRouter initialEntries={['/memories']}>
      <PillNav
        items={[
          { to: '/chat', label: '对话' },
          { to: '/memories', label: '记忆' },
          { to: '/sources', label: '资料' },
        ]}
      />
    </MemoryRouter>,
  );
  const nav = screen.getByRole('navigation', { name: '主导航' });
  expect(nav).toBeVisible();
  expect(screen.getByRole('link', { name: '记忆' })).toHaveAttribute(
    'aria-current',
    'page',
  );
  expect(screen.getByRole('link', { name: '对话' })).not.toHaveAttribute(
    'aria-current',
  );
  expect(screen.getByRole('link', { name: '资料' })).toHaveAttribute(
    'href',
    '/sources',
  );
});

it('opens a source from its chip, and only says where a line is from without one', () => {
  const open = vi.fn();
  render(
    <GlassPanel aria-label="回答">
      <RiseText>两句话都是你的。</RiseText>
      <CitationChip onClick={open}>日记 · 2024-01-27</CitationChip>
      <CitationChip kind="conflict">矛盾 · 2</CitationChip>
    </GlassPanel>,
  );
  expect(screen.getByRole('region', { name: '回答' })).toBeVisible();
  expect(screen.getByText('两句话都是你的。')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '日记 · 2024-01-27' }));
  expect(open).toHaveBeenCalledOnce();
  expect(screen.queryByRole('button', { name: '矛盾 · 2' })).toBeNull();
  expect(screen.getByText('矛盾 · 2')).toBeVisible();
});

it('stands in a still glow for the core where WebGL cannot draw', () => {
  render(<TwinCore pulse={1} label="心核" />);
  const core = screen.getByRole('img', { name: '心核' });
  expect(core.tagName).toBe('DIV');
  expect(core).toHaveClass('twin-core-fallback');
});
