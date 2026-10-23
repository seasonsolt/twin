import { useOutletContext } from 'react-router';

/** What the shell tells the page in it. */
export interface ShellContext {
  /** The account has no twin at all. */
  noTwin: boolean;
}

/** Whether the account has no twin at all, as the shell found. */
export const useNoTwin = () =>
  useOutletContext<ShellContext | undefined>()?.noTwin ?? false;
