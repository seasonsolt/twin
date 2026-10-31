/** One heir as the will keeps them (``persona.will.Heir``). Never holds the word that opens the twin. */
export interface Heir {
  heir_id: string;
  name: string;
  relation: string;
  /** Whole aspects given (``D1``…``D10``). */
  aspects: string[];
  /** Single facets given beyond the whole aspects. */
  facets: string[];
  avoid: string[];
  voice: boolean;
  likeness: boolean;
  retire_on: string | null;
  farewell: string | null;
  /** Up to two things the person said themself, said after the goodbye (ids of ``own_words``). */
  farewell_words?: string[];
  created_at: string;
  updated_at: string;
}

export interface Will {
  heirs: Heir[];
  /** Whether the memory is sealed (P2.5), from a server that says so; otherwise learnt from a refused change. */
  sealed?: boolean;
}

/** One row of the will's history, with the whole will after it. */
export interface WillChange {
  at: string;
  actor: string;
  action: 'add' | 'update' | 'remove' | 'taxonomy';
  heir_id: string;
  changes: string[];
  heirs: Heir[];
}

/** What is sent to name or rewrite an heir. ``password`` only when the person sets it. */
export interface HeirBody {
  name: string;
  relation: string;
  aspects: string[];
  facets: string[];
  avoid: string[];
  voice: boolean;
  likeness: boolean;
  retire_on: string | null;
  farewell: string | null;
  farewell_words: string[];
  password?: string;
}

/** The ten aspects and their facets, by name (from the coverage report). */
export interface Taxonomy {
  dimensions: { dimension_id: string; name: string }[];
  facets: { facet_id: string; name: string; dimension_id: string }[];
}

/** The aspect a facet belongs to: ``2.1`` is of ``D2``. */
export const aspectOf = (facetId: string) => `D${facetId.split('.')[0]}`;

/** How many aspects the will touches for an heir, whole or in part. */
export const aspectCount = (heir: Pick<Heir, 'aspects' | 'facets'>) =>
  new Set([...heir.aspects, ...heir.facets.map(aspectOf)]).size;

// Limits kept by ``persona.will``; checked here too so a mistake is said at the step it is made.
export const MAX_NAME = 20;
export const MAX_TOPICS = 20;
export const MAX_TOPIC = 60;
export const MAX_FAREWELL = 500;
export const MIN_PASSWORD = 6;
export const MAX_PASSWORD = 128;

/** Something the person said themself, offered to leave with an heir after the goodbye. */
export interface OwnWords {
  id: string;
  quote: string;
  date: string | null;
}
export const MAX_FAREWELL_WORDS = 2;
