import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router';
import { Plus } from 'lucide-react';
import {
  ActionMenu,
  Badge,
  Button,
  Dialog,
  Disclosure,
  ListRow,
  Notice,
  Row,
  Skeleton,
  Stack,
  Text,
  useConfirm,
} from '../../components/ui';
import { api, ApiError } from '../../lib/api';
import { useSeesWhole } from '../../stores/access';
import { usePersonaEdition } from '../../stores/auth';
import { usePersonas } from '../../stores/personas';
import { HeirEditor } from './HeirEditor';
import { HeirPreview } from './HeirPreview';
import {
  aspectCount,
  type Heir,
  type HeirBody,
  type Taxonomy,
  type Will as WillState,
  type WillChange,
} from './types';

/** The search parameter that opens the will over any page; closing it returns there. */
export const WILL_PARAM = 'will';

/** Opens the will over the current page. */
export function useOpenWill() {
  const [, setParams] = useSearchParams();
  return useCallback(
    () =>
      setParams((params) => {
        params.set(WILL_PARAM, '');
        return params;
      }),
    [setParams],
  );
}

/** Whether the viewer may keep a will: the person behind the twin, in the persona edition. */
export function useKeepsWill() {
  const persona = usePersonaEdition();
  const whole = useSeesWhole(
    usePersonas((state) => state.items.find((item) => item.id === state.id)),
  );
  return persona && whole;
}

const sealedRefusal = (failure: unknown) =>
  failure instanceof ApiError &&
  failure.status === 423 &&
  failure.code === 'memory_sealed';

const message = (failure: unknown) =>
  failure instanceof Error ? failure.message : String(failure);

const FIELD_LABELS: Record<string, string> = {
  name: '称呼',
  relation: '关系',
  aspects: '方面',
  facets: '方面',
  avoid: '不谈',
  voice: '声音',
  likeness: '形象',
  retire_on: '退场',
  farewell: '告别语',
  password: '口令',
};

/** One change, in a few words: what was done to whom, and which parts. */
function describe(change: WillChange, name: string) {
  if (change.action === 'add') return `加了${name}`;
  if (change.action === 'remove') return `删了${name}`;
  if (change.action === 'taxonomy') return `${name}的方面随分类升级`;
  const parts = [
    ...new Set(change.changes.map((field) => FIELD_LABELS[field] ?? field)),
  ];
  return parts.length ? `改了${name}：${parts.join('、')}` : `改了${name}`;
}

/** Every change to the will, newest first, folded until asked for. */
function History({ changes }: { changes: WillChange[] }) {
  // A removed heir is no longer in the will after the change: their name comes from before it.
  const names = new Map<string, string>();
  for (const change of changes)
    for (const heir of change.heirs) names.set(heir.heir_id, heir.name);
  return (
    <Disclosure
      variant="plain"
      summary={
        <Text as="span" size="sm" tone="secondary">
          改动记录 {changes.length}
        </Text>
      }
    >
      <Stack as="ol" gap={0} aria-label="改动记录">
        {[...changes].reverse().map((change, index) => (
          <ListRow
            key={`${change.at}-${index}`}
            variant="divided"
            title={
              <Text as="span" size="sm">
                {describe(change, names.get(change.heir_id) ?? '继承人')}
              </Text>
            }
            meta={change.at.slice(0, 16).replace('T', ' ')}
          />
        ))}
      </Stack>
    </Disclosure>
  );
}

function HeirRow({
  heir,
  sealed,
  onEdit,
  onRehearse,
  onRemove,
}: {
  heir: Heir;
  sealed: boolean;
  onEdit: () => void;
  onRehearse: () => void;
  onRemove: () => void;
}) {
  const count = aspectCount(heir);
  return (
    <ListRow
      variant="divided"
      title={heir.name}
      meta={
        <Row gap={2} wrap>
          {heir.relation && <Text as="span">{heir.relation}</Text>}
          <Badge tone={count ? 'neutral' : 'warning'}>
            {count ? `${count} 个方面` : '什么都不给'}
          </Badge>
          {heir.retire_on && <Badge>至 {heir.retire_on}</Badge>}
        </Row>
      }
      trailing={
        <ActionMenu
          label={`${heir.name}的操作`}
          items={[
            { label: '修改', onSelect: onEdit, disabled: sealed },
            { label: '预演', onSelect: onRehearse, disabled: sealed },
            {
              label: '删除',
              onSelect: onRemove,
              disabled: sealed,
              danger: true,
            },
          ]}
        />
      }
    />
  );
}

/**
 * 数字遗嘱 (P2.3): who may talk with the twin after the person, about what and until when, kept by the person alone
 * in a side layer over whatever page they were on. Each heir is a row; naming or changing one is done a step at a
 * time in the same layer, and so is rehearsing what the heir would be answered (预演). Once the memory is sealed the will stays as it was left and nothing here can change it.
 */
export function Will() {
  const keeps = useKeepsWill();
  const [params, setParams] = useSearchParams();
  const open = keeps && params.get(WILL_PARAM) !== null;
  const confirm = useConfirm();
  const [will, setWill] = useState<WillState | null>(null);
  const [changes, setChanges] = useState<WillChange[]>([]);
  const [error, setError] = useState('');
  const [sealed, setSealed] = useState(false);
  // The heir being named (null) or changed; undefined while the list shows.
  const [editing, setEditing] = useState<Heir | null | undefined>(undefined);
  // The heir whose conversation the person is rehearsing (预演), if any.
  const [rehearsing, setRehearsing] = useState<Heir | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [taxonomy, setTaxonomy] = useState<Taxonomy | null>(null);
  const [taxonomyError, setTaxonomyError] = useState('');
  const loading = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    loading.current?.abort();
    const controller = new AbortController();
    loading.current = controller;
    try {
      const [read, history] = await Promise.all([
        api<WillState>('/api/persona/will', { signal: controller.signal }),
        api<{ changes: WillChange[] }>('/api/persona/will/history', {
          signal: controller.signal,
        }),
      ]);
      setWill(read);
      setChanges(history.changes);
      if (read.sealed) setSealed(true);
      setError('');
    } catch (failure) {
      if (!controller.signal.aborted) setError(message(failure));
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    setWill(null);
    setError('');
    setEditing(undefined);
    setRehearsing(null);
    void load();
    return () => loading.current?.abort();
  }, [open, load]);

  // The aspects and facets by name, once, when the first heir is named or changed.
  const editingOpen = editing !== undefined;
  useEffect(() => {
    if (!editingOpen || taxonomy) return;
    const controller = new AbortController();
    setTaxonomyError('');
    api<Taxonomy>('/api/persona/coverage', { signal: controller.signal })
      .then((report) =>
        setTaxonomy({
          dimensions: report.dimensions,
          facets: report.facets,
        }),
      )
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) setTaxonomyError(message(failure));
      });
    return () => controller.abort();
  }, [editingOpen, taxonomy]);

  const close = () =>
    setParams(
      (current) => {
        current.delete(WILL_PARAM);
        return current;
      },
      { replace: true },
    );

  // A refused change because the memory is sealed: nothing here can change the will any more.
  const refused = (failure: unknown) => {
    if (!sealedRefusal(failure)) return false;
    setSealed(true);
    setEditing(undefined);
    setRehearsing(null);
    return true;
  };

  // A rehearsal refused: sealed meanwhile, or the heir taken out elsewhere; back to the will as it now stands.
  const rehearsalRefused = (failure: unknown) => {
    if (refused(failure)) return true;
    if (!(failure instanceof ApiError) || failure.status !== 404) return false;
    setRehearsing(null);
    void load();
    return true;
  };

  const save = async (body: HeirBody) => {
    setSaving(true);
    setSaveError('');
    try {
      await api(
        editing
          ? `/api/persona/will/heirs/${encodeURIComponent(editing.heir_id)}`
          : '/api/persona/will/heirs',
        { method: editing ? 'PUT' : 'POST', json: body },
      );
      setEditing(undefined);
      await load();
    } catch (failure) {
      if (!refused(failure)) setSaveError(message(failure));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (heir: Heir) => {
    const ok = await confirm({
      title: `删除${heir.name}？`,
      body: '身后不再回答这位继承人，改动记录里仍留着。',
      confirmLabel: '删除',
      tone: 'danger',
    });
    if (!ok) return;
    try {
      await api(`/api/persona/will/heirs/${encodeURIComponent(heir.heir_id)}`, {
        method: 'DELETE',
      });
      await load();
    } catch (failure) {
      if (!refused(failure)) setError(message(failure));
    }
  };

  const edit = (heir: Heir | null) => {
    setSaveError('');
    setRehearsing(null);
    setEditing(heir);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => !next && close()}
      title={
        editing !== undefined
          ? (editing?.name ?? '加继承人')
          : rehearsing
            ? `预演 · ${rehearsing.name}`
            : '数字遗嘱'
      }
      variant="side"
    >
      {editing !== undefined ? (
        <HeirEditor
          key={editing?.heir_id ?? 'new'}
          heir={editing}
          taxonomy={taxonomy}
          taxonomyError={taxonomyError}
          saving={saving}
          error={saveError}
          onSave={(body) => void save(body)}
          onCancel={() => setEditing(undefined)}
        />
      ) : rehearsing ? (
        <HeirPreview
          key={rehearsing.heir_id}
          heir={rehearsing}
          onEdit={() => edit(rehearsing)}
          onBack={() => setRehearsing(null)}
          onRefused={rehearsalRefused}
        />
      ) : (
        <Stack gap={4}>
          {sealed && <Notice tone="info">已冻结，遗嘱不能再改</Notice>}
          {error && (
            <Notice tone="danger" role="alert">
              {error}
            </Notice>
          )}
          {!will ? (
            !error && (
              <Stack gap={2}>
                <Skeleton />
                <Skeleton />
              </Stack>
            )
          ) : (
            <>
              {will.heirs.length ? (
                <Stack as="ul" gap={0} aria-label="继承人">
                  {will.heirs.map((heir) => (
                    <HeirRow
                      key={heir.heir_id}
                      heir={heir}
                      sealed={sealed}
                      onEdit={() => edit(heir)}
                      onRehearse={() => {
                        setError('');
                        setRehearsing(heir);
                      }}
                      onRemove={() => void remove(heir)}
                    />
                  ))}
                </Stack>
              ) : (
                <Text tone="secondary">
                  还没有继承人。没写进遗嘱的，身后一律不给。
                </Text>
              )}
              <Row>
                <Button
                  variant={will.heirs.length ? 'secondary' : 'primary'}
                  disabled={sealed}
                  onClick={() => edit(null)}
                >
                  <Plus aria-hidden className="size-4" />
                  加继承人
                </Button>
              </Row>
              {changes.length > 0 && <History changes={changes} />}
            </>
          )}
        </Stack>
      )}
    </Dialog>
  );
}
