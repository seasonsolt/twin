import { renderHook } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { useCanManage, useManagesCurrent } from '../stores/access';
import { useAuth, type Identity } from '../stores/auth';
import { usePersonas, type Persona } from '../stores/personas';

const twin = (change: Partial<Persona>): Persona => ({
  id: 'p-1',
  name: '林舟',
  avatar_url: null,
  sources: 1,
  created_at: '',
  is_default: false,
  ...change,
});
const identity = (admin: boolean): Identity => ({
  email: 'me@example.test',
  admin,
  auth_enabled: true,
});
const set = (admin: boolean, id: string, items: Persona[]) => {
  useAuth.setState({ identity: identity(admin) });
  usePersonas.setState({ id, items });
};

afterEach(() => {
  useAuth.setState({ identity: null });
  usePersonas.setState({ id: '', items: [] });
});

it('treats someone who only meets twins others made public as a guest', () => {
  set(false, 'p-pub', [
    twin({ id: 'p-pub', name: '朋友', can_manage: false }),
    twin({ id: 'p-pub2', name: '另一位', can_manage: false }),
  ]);
  expect(renderHook(() => useCanManage()).result.current).toBe(false);
});

it('lets an administrator run the team even when every twin in view is someone else’s', () => {
  set(true, 'p-pub', [twin({ id: 'p-pub', can_manage: false })]);
  expect(renderHook(() => useCanManage()).result.current).toBe(true);
});

it('lets a person with a twin of their own run the team while another twin is in view', () => {
  set(false, 'p-pub', [
    twin({ id: 'p-pub', name: '朋友', can_manage: false }),
    twin({ id: 'p-own', name: '我', can_manage: true, mine: true }),
  ]);
  expect(renderHook(() => useCanManage()).result.current).toBe(true);
  // What the twin in view remembers is still only for the person behind it.
  expect(renderHook(() => useManagesCurrent()).result.current).toBe(false);
});

it('does not make a guest of someone with no twin yet, who is offered to make one', () => {
  set(false, '', []);
  expect(renderHook(() => useCanManage()).result.current).toBe(true);
});

it('counts a twin from an older server, which does not say, as one to manage', () => {
  set(false, 'p-1', [twin({})]);
  expect(renderHook(() => useCanManage()).result.current).toBe(true);
});
