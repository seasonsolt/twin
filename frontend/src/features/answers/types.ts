/** A team answer as a colleague (or a twin) is shown it: whose it is and the day they confirmed it, never who asked. */
export interface TeamAnswerCard {
  id: string;
  /** The twin of the person who confirmed it. */
  persona_id: string;
  owner_name: string;
  title: string;
  body: string;
  confirmed_at: string;
  status: 'valid' | 'stale' | 'withdrawn';
  /** What the person said since that does not agree: the day, where, and what. */
  stale_note: string;
  /** It answers only part of what was asked. */
  partial: boolean;
}

/** A team answer as the person who set it sees it. */
export interface MyTeamAnswer extends TeamAnswerCard {
  handoff_id: string | null;
}

/** 10 月 22 日 from an ISO time. */
export function dayOf(iso: string): string {
  const match = /^\d{4}-(\d{2})-(\d{2})/.exec(iso);
  return match ? `${Number(match[1])} 月 ${Number(match[2])} 日` : '';
}

export const confirmedText = (card: TeamAnswerCard) =>
  `${card.owner_name} ${dayOf(card.confirmed_at)}确认`;
