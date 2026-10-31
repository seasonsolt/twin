import { create } from 'zustand';
import { api, beginApiSession } from '../lib/api';
import { browser } from '../lib/base';
import { adoptPersonaId, setHeirKeys } from '../lib/persona';
import { clearPrefetch } from '../lib/personaPrefetch';
import { usePersonas } from './personas';
import { useWelcome } from './welcome';

export interface Identity {
  email: string | null;
  /** Display name from single sign-on; email login has none. */
  name?: string | null;
  /** The work e-mail of the account, by which a twin made for it is taken. */
  address?: string | null;
  /** The name the company sign-in gives the account (an employee number), which takes a twin made for it too. */
  account?: string | null;
  admin: boolean;
  auth_enabled: boolean;
  /** How the server signs people in; 'sso' borrows another app's sign-in on this site. */
  provider?: 'email' | 'sso' | 'password' | null;
  /** Pages an administrator switched on or off for everyone; missing (an older server) means on. */
  features?: Partial<Record<Feature, boolean>>;
  /** The team's name, set in the system settings; none until an administrator names it. */
  team_name?: string | null;
  /** Which product the server runs (``[product] edition``); missing (an older server) means the team's. */
  edition?: Edition;
  /** An heir who opened the twin with their word (P2.7): this browser is theirs, to their own conversation alone. */
  heir?: Heir | null;
  /** The person's own twin is sealed (P2.7): this computer is only the heirs' way in now. */
  sealed?: boolean;
}

/** The heir in this browser, as ``/api/whoami`` says. */
export interface Heir {
  id: string;
  name: string;
  /** The name the twin keeps for its person; none when they never gave one. */
  person: string | null;
  /** The twin they opened. */
  persona: string;
  /** The twin has said goodbye to them (P2.8): their conversations are only to read. */
  gone?: boolean;
}

/** The heir in this browser, if one is in. */
export const useHeir = () => useAuth((state) => state.identity?.heir ?? null);

/** 'persona': one person's own twin on their own machine, with chat and its memories only; 'team': everything. */
export type Edition = 'persona' | 'team';

export const personaEdition = (identity: Identity | null) =>
  identity?.edition === 'persona';

/** Whether this is the persona edition, where the team's pages are not there. */
export const usePersonaEdition = () =>
  useAuth((state) => personaEdition(state.identity));

/** Pages that can be switched off. Chat is the twin itself and never is. */
export type Feature = 'work' | 'ledger';

export const featureOn = (identity: Identity | null, feature: Feature) =>
  identity?.features?.[feature] !== false;

/** After an administrator switched a page, show it or hide it at once, without signing in again. */
export function setFeatures(features: Partial<Record<Feature, boolean>>) {
  useAuth.setState((state) => ({
    identity: state.identity && {
      ...state.identity,
      features: { ...state.identity.features, ...features },
    },
  }));
}

/** After an administrator named the team, show it at once, without signing in again. */
export function setTeamName(name: string | null) {
  useAuth.setState((state) => ({
    identity: state.identity && { ...state.identity, team_name: name },
  }));
}

export const accountLabel = (identity: Identity) =>
  identity.name || identity.email || '';
let version = 0;
export const useAuth = create<{
  identity: Identity | null;
  /** Signed out on purpose: the next person to sign in starts afresh, not on the page the last one had open. */
  signedOut: boolean;
  login: (signal?: AbortSignal) => Promise<void>;
  logout: () => Promise<void>;
  leave: () => Promise<void>;
  clear: () => void;
}>((set, get) => ({
  identity: null,
  signedOut: false,
  clear() {
    ++version;
    beginApiSession();
    set({ identity: null });
    setHeirKeys('');
    usePersonas.getState().reset();
    useWelcome.getState().reset();
  },
  async login(signal) {
    const current = ++version;
    beginApiSession();
    const identity = await api<Identity>('/api/whoami', { signal });
    if (signal?.aborted || current !== version) return;
    if (identity.heir) {
      // An heir reaches their twin alone and no list of twins.
      clearPrefetch();
      setHeirKeys(identity.heir.id);
      adoptPersonaId(identity.heir.persona);
      usePersonas.setState({
        id: identity.heir.persona,
        items: [],
        pendingId: null,
      });
    } else if (identity.sealed) {
      // Sealed, the person's twins are shown to no one but the heirs, through their own way in.
      setHeirKeys('');
      clearPrefetch();
      usePersonas.setState({ items: [], pendingId: null });
    } else {
      setHeirKeys('');
      await usePersonas.getState().refresh();
    }
    if (!signal?.aborted && current === version)
      set({ identity, signedOut: false });
  },
  /** The heir leaves: their session ends on the server and this browser forgets it. */
  async leave() {
    await api('/api/heir/leave', { method: 'POST' });
    get().clear();
    await get().login();
  },
  async logout() {
    const current = version;
    const out = await api<{ redirect?: string | null } | null>(
      '/api/auth/logout',
      { method: 'POST' },
    );
    if (current !== version) return;
    set({ signedOut: true });
    get().clear();
    // The company sign-in keeps its own session; its sign-out ends it and comes back to twin's sign-in page.
    if (out?.redirect) browser.leave(out.redirect);
  },
}));
