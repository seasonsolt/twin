import { useState } from 'react';
import { CircleHelp } from 'lucide-react';
import {
  Button,
  CheckGroup,
  Field,
  IconButton,
  Input,
  Notice,
  Row,
  Skeleton,
  Stack,
  Steps,
  Switch,
  Text,
  Textarea,
  Tooltip,
} from '../../components/ui';
import {
  aspectOf,
  MAX_FAREWELL,
  MAX_NAME,
  MAX_PASSWORD,
  MAX_TOPIC,
  MAX_TOPICS,
  MIN_PASSWORD,
  type Heir,
  type HeirBody,
  type Taxonomy,
} from './types';

const STEPS = ['称呼', '方面', '不谈', '声音影像', '退场', '口令'];
const LAST = STEPS.length - 1;

interface Draft {
  name: string;
  relation: string;
  aspects: string[];
  facets: string[];
  avoid: string;
  voice: boolean;
  likeness: boolean;
  retire_on: string;
  farewell: string;
  password: string;
  again: string;
}

const draftOf = (heir: Heir | null): Draft => ({
  name: heir?.name ?? '',
  relation: heir?.relation ?? '',
  // Nothing is given unless the person ticks it.
  aspects: heir?.aspects ?? [],
  facets: heir?.facets ?? [],
  avoid: heir?.avoid.join('\n') ?? '',
  voice: heir?.voice ?? false,
  likeness: heir?.likeness ?? false,
  retire_on: heir?.retire_on ?? '',
  farewell: heir?.farewell ?? '',
  password: '',
  again: '',
});

const topics = (text: string) =>
  text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);

/** What is wrong at a step, if anything; said at that step, before going on. */
function problem(step: number, draft: Draft, adding: boolean): string {
  if (step === 0) {
    if (!draft.name.trim()) return '写一个称呼';
    if (draft.name.trim().length > MAX_NAME)
      return `称呼不超过 ${MAX_NAME} 个字`;
    if (draft.relation.trim().length > MAX_NAME)
      return `关系不超过 ${MAX_NAME} 个字`;
  }
  if (step === 2) {
    const kept = topics(draft.avoid);
    if (kept.length > MAX_TOPICS) return `最多 ${MAX_TOPICS} 条`;
    if (kept.some((topic) => topic.length > MAX_TOPIC))
      return `每条不超过 ${MAX_TOPIC} 个字`;
  }
  if (step === 4 && draft.farewell.trim().length > MAX_FAREWELL)
    return `告别语不超过 ${MAX_FAREWELL} 个字`;
  if (step === 5) {
    // On a change both left empty keep the word as it is.
    if (!adding && !draft.password && !draft.again) return '';
    if (draft.password.length < MIN_PASSWORD)
      return `口令至少 ${MIN_PASSWORD} 个字`;
    if (draft.password.length > MAX_PASSWORD)
      return `口令不超过 ${MAX_PASSWORD} 个字`;
    if (draft.password !== draft.again) return '两次输入的口令不一样';
  }
  return '';
}

function bodyOf(draft: Draft): HeirBody {
  const farewell = draft.farewell.trim();
  return {
    name: draft.name.trim(),
    relation: draft.relation.trim(),
    aspects: draft.aspects,
    facets: draft.facets,
    avoid: topics(draft.avoid),
    voice: draft.voice,
    likeness: draft.likeness,
    retire_on: draft.retire_on || null,
    farewell: farewell || null,
    // The word goes out only when the person sets it, and only in this request.
    ...(draft.password ? { password: draft.password } : {}),
  };
}

/** The ten aspects, each opening to its facets. Ticking a whole aspect gives what it holds now and later. */
function Aspects({
  taxonomy,
  draft,
  onChange,
  disabled,
}: {
  taxonomy: Taxonomy;
  draft: Draft;
  onChange: (next: Pick<Draft, 'aspects' | 'facets'>) => void;
  disabled: boolean;
}) {
  const facetsOf = (aspect: string) =>
    taxonomy.facets.filter((facet) => facet.dimension_id === aspect);
  const setWhole = (aspect: string, checked: boolean) =>
    onChange({
      aspects: checked
        ? [...draft.aspects, aspect]
        : draft.aspects.filter((id) => id !== aspect),
      facets: draft.facets.filter((id) => aspectOf(id) !== aspect),
    });
  const setFacet = (aspect: string, facetId: string, checked: boolean) => {
    const all = facetsOf(aspect).map((facet) => facet.facet_id);
    const whole = draft.aspects.includes(aspect);
    if (whole && checked) return;
    // Taking one facet out of a whole aspect leaves the others given one by one.
    const chosen = whole
      ? all.filter((id) => id !== facetId)
      : checked
        ? [...draft.facets.filter((id) => aspectOf(id) === aspect), facetId]
        : draft.facets.filter(
            (id) => aspectOf(id) === aspect && id !== facetId,
          );
    const others = draft.facets.filter((id) => aspectOf(id) !== aspect);
    const aspects = draft.aspects.filter((id) => id !== aspect);
    // Every facet ticked one by one is the whole aspect.
    if (chosen.length === all.length && all.length > 0)
      onChange({ aspects: [...aspects, aspect], facets: others });
    else onChange({ aspects, facets: [...others, ...chosen] });
  };
  return (
    <Stack gap={0} role="group" aria-label="能用的方面">
      {taxonomy.dimensions.map((dimension) => (
        <CheckGroup
          key={dimension.dimension_id}
          label={dimension.name}
          whole={draft.aspects.includes(dimension.dimension_id)}
          disabled={disabled}
          items={facetsOf(dimension.dimension_id).map((facet) => ({
            id: facet.facet_id,
            label: facet.name,
            checked: draft.facets.includes(facet.facet_id),
          }))}
          onWholeChange={(checked) => setWhole(dimension.dimension_id, checked)}
          onItemChange={(id, checked) =>
            setFacet(dimension.dimension_id, id, checked)
          }
        />
      ))}
    </Stack>
  );
}

/** A question mark that says on hover what need not stand on the page. */
function Help({ label }: { label: string }) {
  return (
    <Tooltip label={label}>
      <IconButton label={`说明：${label}`} shape="circle">
        <CircleHelp className="size-4" aria-hidden />
      </IconButton>
    </Tooltip>
  );
}

/**
 * Naming an heir or changing one, a step at a time: who they are, what of the person they may use, what is never
 * talked about, voice and likeness, when it ends, and the word that opens the twin to them. The word is typed twice,
 * never shown, and sent only when set; on a change, leaving it empty keeps the one there is.
 */
export function HeirEditor({
  heir,
  taxonomy,
  taxonomyError,
  saving,
  error,
  onSave,
  onCancel,
}: {
  /** The heir being changed; null names a new one. */
  heir: Heir | null;
  taxonomy: Taxonomy | null;
  taxonomyError: string;
  saving: boolean;
  /** Why the server refused the last save. */
  error: string;
  onSave: (body: HeirBody) => void;
  onCancel: () => void;
}) {
  const adding = heir === null;
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState(() => draftOf(heir));
  const [shown, setShown] = useState('');
  const set = (next: Partial<Draft>) => {
    setDraft((current) => ({ ...current, ...next }));
    setShown('');
  };
  const checked = (to: number) => {
    const wrong = problem(step, draft, adding);
    setShown(wrong);
    if (!wrong) setStep(to);
  };
  const save = () => {
    // Every step is checked: on a change the person may save from any of them.
    for (let at = 0; at <= LAST; at += 1) {
      const wrong = problem(at, draft, adding);
      if (wrong) {
        setStep(at);
        setShown(wrong);
        return;
      }
    }
    onSave(bodyOf(draft));
  };
  const message = shown || error;
  return (
    <Stack gap={5}>
      <Steps label="步骤" steps={STEPS} current={step} compact />
      {step === 0 && (
        <Stack gap={4}>
          <Field id="heir-name" label="称呼">
            <Input
              id="heir-name"
              value={draft.name}
              maxLength={MAX_NAME}
              autoFocus
              onChange={(event) => set({ name: event.target.value })}
            />
          </Field>
          <Field id="heir-relation" label="关系">
            <Input
              id="heir-relation"
              value={draft.relation}
              maxLength={MAX_NAME}
              placeholder="女儿、老友"
              onChange={(event) => set({ relation: event.target.value })}
            />
          </Field>
        </Stack>
      )}
      {step === 1 && (
        <Stack gap={2}>
          <Row gap={1}>
            <Text weight="medium">能用的方面</Text>
            <Help label="没勾的身后一律不给" />
          </Row>
          {taxonomyError ? (
            <Notice tone="danger" role="alert">
              {taxonomyError}
            </Notice>
          ) : !taxonomy ? (
            <Stack gap={2}>
              <Skeleton />
              <Skeleton />
            </Stack>
          ) : (
            <Aspects
              taxonomy={taxonomy}
              draft={draft}
              disabled={saving}
              onChange={set}
            />
          )}
        </Stack>
      )}
      {step === 2 && (
        <Field id="heir-avoid" label="不谈的话题">
          <Textarea
            id="heir-avoid"
            value={draft.avoid}
            rows={4}
            maxRows={8}
            placeholder={'一行一条\n前一段婚姻'}
            onChange={(event) => set({ avoid: event.target.value })}
          />
        </Field>
      )}
      {step === 3 && (
        <Stack gap={4}>
          <Switch
            label="用我的声音"
            checked={draft.voice}
            onCheckedChange={(voice) => set({ voice })}
          />
          <Switch
            label="用我的形象"
            checked={draft.likeness}
            onCheckedChange={(likeness) => set({ likeness })}
          />
        </Stack>
      )}
      {step === 4 && (
        <Stack gap={4}>
          <Field id="heir-retire" label="退场日期">
            <Input
              id="heir-retire"
              type="date"
              value={draft.retire_on}
              onChange={(event) => set({ retire_on: event.target.value })}
            />
          </Field>
          <Field id="heir-farewell" label="告别语">
            <Textarea
              id="heir-farewell"
              value={draft.farewell}
              rows={3}
              maxRows={6}
              placeholder="不写就用默认的"
              onChange={(event) => set({ farewell: event.target.value })}
            />
          </Field>
        </Stack>
      )}
      {step === 5 && (
        <Stack gap={4}>
          <Field id="heir-password" label="开启口令">
            <Input
              id="heir-password"
              type="password"
              autoComplete="new-password"
              value={draft.password}
              maxLength={MAX_PASSWORD}
              placeholder={adding ? undefined : '留空不改'}
              onChange={(event) => set({ password: event.target.value })}
            />
          </Field>
          <Field id="heir-again" label="再输一次">
            <Input
              id="heir-again"
              type="password"
              autoComplete="new-password"
              value={draft.again}
              maxLength={MAX_PASSWORD}
              onChange={(event) => set({ again: event.target.value })}
            />
          </Field>
        </Stack>
      )}
      {message && (
        <Notice tone="danger" role="alert">
          {message}
        </Notice>
      )}
      <Row justify="between">
        {step === 0 ? (
          <Button variant="ghost" onClick={onCancel}>
            取消
          </Button>
        ) : (
          <Button
            variant="ghost"
            onClick={() => {
              setShown('');
              setStep(step - 1);
            }}
          >
            上一步
          </Button>
        )}
        <Row gap={2}>
          {step < LAST && (
            <Button
              variant={adding ? 'primary' : 'secondary'}
              onClick={() => checked(step + 1)}
            >
              下一步
            </Button>
          )}
          {(!adding || step === LAST) && (
            <Button variant="primary" loading={saving} onClick={save}>
              保存
            </Button>
          )}
        </Row>
      </Row>
    </Stack>
  );
}
