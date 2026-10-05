export const kindOptions = [
  [
    'questionnaire',
    '问卷',
    '建档问卷导出的文字（每题“回答：”下面是答案）',
    '.txt,.md',
  ],
  [
    'meeting',
    '转录文本',
    '有说话人的 TXT / Markdown / SRT / VTT / JSON；文件名含日期',
    '.txt,.md,.srt,.vtt,.json',
  ],
  [
    'chat',
    '聊天记录',
    '每行“时间 发言人：内容”，或微信式分块，或 CSV / JSON',
    '.txt,.csv,.json',
  ],
  [
    'interview',
    '访谈',
    '每行“说话人：内容”的访谈稿，日期写在文件名里',
    '.txt,.md',
  ],
  [
    'document',
    '文档与邮件',
    '本人写的方案、周报、邮件，按段落导入',
    '.txt,.md',
  ],
  [
    'biography',
    '传记与他人记述',
    '别人写的关于本人的传记、年谱、报道；标题里的年份作为下面段落的日期',
    '.txt,.md',
  ],
] as const;
export type SourceKind = (typeof kindOptions)[number][0];
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
