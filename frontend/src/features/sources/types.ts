export type SourceKind = 'questionnaire' | 'chat' | 'interview' | 'document';
export interface Source {
  source_id: string;
  title: string;
  kind: SourceKind;
  kind_label: string;
  evidence_class: string;
  n_target: number;
  n_expressions: number;
  first_date: string | null;
  last_date: string | null;
  expressions_total?: number;
  expressions_target?: number;
  expressions_others?: number;
  items_supported?: number;
  facets?: { facet_id: string; name: string }[];
  build_status?: 'not_built' | 'remembered' | 'no_items';
  declined_facets: string[];
}
export interface ImportResult {
  imported: (Source & { new: boolean })[];
  skipped: { file: string; reason: string }[];
}
export interface BuildResult {
  sources?: number;
  chunks_extracted?: number;
  candidates?: number;
  items?: number;
  failures?: string[];
  items_added?: number;
  items_changed?: number;
  items_removed?: number;
  facets_changed?: number;
  facet_diffs?: Record<
    string,
    { added: number; changed: number; removed: number }
  >;
}
export const staleNotice = '资料有变化，尚未重新构建；档案和聊天仍基于上次构建';
