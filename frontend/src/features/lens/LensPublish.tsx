import { useEffect, useMemo, useState } from 'react';
import { api } from '../../lib/api';
import {
  Badge,
  Button,
  Card,
  Checkbox,
  Dialog,
  Disclosure,
  Field,
  Heading,
  Input,
  LevelDots,
  Radio,
  Row,
  Stack,
  Text,
} from '../../components/ui';
import { useTeam } from '../../stores/team';
import { LensStatements } from './LensStatements';
import {
  aspectsOf,
  type Aspect,
  type Lens,
  type LensList,
  type LensStatement,
} from './types';

const NAME_MAX = 20;

/**
 * 发布赋能, a layer beside the page: a name, the aspects to open (one tick each; only those with a well-founded facet
 * can be ticked, the rest are one folded line), whom it is for, and a preview of how it reads. An aspect opens all its
 * facets: the lens speaks from those well founded and the others join as the twin learns them. With `lens` it adjusts
 * one that is published: an aspect with a facet corrected out shows 已停用 and keeps that facet out; ticking the aspect
 * again (off, then on) opens it afresh.
 */
export function LensPublish({
  open,
  onClose,
  onDone,
  person,
  twinId,
  data,
  lens,
}: {
  open: boolean;
  onClose: () => void;
  onDone: () => Promise<void> | void;
  /** The person's name, for the preview. */
  person: string;
  /** The person's own twin, left out of the people to choose. */
  twinId: string;
  data: LensList;
  lens?: Lens;
}) {
  const people = useTeam((state) => state.people);
  const aspects = useMemo(() => aspectsOf(data.facets), [data.facets]);
  // Facets corrected out, and the aspects they belong to.
  const off = useMemo(
    () => new Set(lens?.stopped.map((s) => s.facet_id) ?? []),
    [lens],
  );
  const stopped = useMemo(
    () =>
      new Set(
        aspects
          .filter((a) => a.facets.some((f) => off.has(f.facet_id)))
          .map((a) => a.id),
      ),
    [aspects, off],
  );
  // Aspects ticked here: opened afresh, so what was corrected out of them is opened again.
  const [fresh, setFresh] = useState<Set<string>>(() => new Set());
  const [name, setName] = useState(lens?.name ?? '');
  const [chosen, setChosen] = useState<Set<string>>(
    () =>
      new Set(
        (lens?.facets ?? [])
          .filter((f) => !lens?.stopped.some((s) => s.facet_id === f.facet_id))
          .map((f) => f.dimension_id),
      ),
  );
  const [scope, setScope] = useState<'team' | 'people'>(
    lens?.audience.scope ?? 'team',
  );
  const [twins, setTwins] = useState<Set<string>>(
    () => new Set(lens?.audience.twins ?? []),
  );
  const [views, setViews] = useState<LensStatement[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const openable = aspects.filter((aspect) => aspect.ok);
  const blocked = aspects.filter((aspect) => !aspect.ok);
  const colleagues = (people ?? []).filter(
    (p) => p.persona_id && p.persona_id !== twinId,
  );
  const picked = openable
    .filter((aspect) => chosen.has(aspect.id))
    .flatMap((aspect) =>
      aspect.facets
        .filter((facet) => fresh.has(aspect.id) || !off.has(facet.facet_id))
        .map((facet) => facet.facet_id),
    );
  // How it would read, for the facets ticked; asked again a moment after the ticks change.
  const pickedKey = picked.join();
  useEffect(() => {
    if (!open || !pickedKey) {
      setViews([]);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      api<{ views: LensStatement[] }>('/api/persona/lenses/preview', {
        method: 'POST',
        json: { facets: pickedKey.split(',') },
        signal: controller.signal,
      })
        .then((found) => setViews(found.views))
        .catch(() => {
          if (!controller.signal.aborted) setViews([]);
        });
    }, 250);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [open, pickedKey]);
  const toggle = (id: string, on: boolean) => {
    const flip = (now: Set<string>) => {
      const next = new Set(now);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    };
    setChosen(flip);
    setFresh(flip);
  };
  const toggleTwin = (id: string, on: boolean) =>
    setTwins((now) => {
      const next = new Set(now);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  const ready =
    name.trim().length > 0 &&
    picked.length > 0 &&
    (scope === 'team' || twins.size > 0);
  const save = async () => {
    setBusy(true);
    setError('');
    const audience = { scope, twins: scope === 'people' ? [...twins] : [] };
    try {
      if (lens)
        await api(`/api/persona/lenses/${encodeURIComponent(lens.id)}`, {
          method: 'PATCH',
          json: { name: name.trim(), facets: picked, audience },
        });
      else
        await api('/api/persona/lenses', {
          method: 'POST',
          json: { name: name.trim(), facets: picked, audience },
        });
      await onDone();
      onClose();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '没能保存');
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => !next && onClose()}
      title={lens ? '调整范围' : '发布赋能'}
      variant="side"
    >
      <Stack gap={5}>
        <Field label="名字" id="lens-name">
          <Input
            id="lens-name"
            value={name}
            maxLength={NAME_MAX}
            placeholder="大客户谈判"
            onChange={(event) => setName(event.target.value)}
          />
        </Field>
        <Stack gap={2} role="group" aria-label="开放哪些方面">
          <Heading level={3} size="item">
            开放哪些方面
          </Heading>
          {openable.length === 0 && (
            <Text size="sm" tone="secondary">
              还没有哪个方面够格开放。
            </Text>
          )}
          {openable.map((aspect) => (
            <AspectChoice
              key={aspect.id}
              aspect={aspect}
              checked={chosen.has(aspect.id)}
              stopped={stopped.has(aspect.id)}
              onChange={(on) => toggle(aspect.id, on)}
            />
          ))}
          {blocked.length > 0 && (
            <Disclosure
              variant="plain"
              summary={
                <Text as="span" size="sm" tone="secondary">
                  另有 {blocked.length} 个方面还不能开放
                </Text>
              }
            >
              <Text size="sm" tone="secondary">
                {blocked.map((a) => `${a.name}：${a.reason}`).join('；')}
              </Text>
            </Disclosure>
          )}
        </Stack>
        <Stack gap={2} role="group" aria-label="给谁用">
          <Heading level={3} size="item">
            给谁用
          </Heading>
          <Radio
            name="lens-audience"
            label="全团队"
            checked={scope === 'team'}
            onChange={() => setScope('team')}
          />
          <Radio
            name="lens-audience"
            label="指定的人"
            checked={scope === 'people'}
            onChange={() => setScope('people')}
          />
          {scope === 'people' &&
            colleagues.map((p) => (
              <Checkbox
                key={p.id}
                label={p.name}
                checked={twins.has(p.persona_id ?? '')}
                onChange={(event) =>
                  toggleTwin(p.persona_id ?? '', event.target.checked)
                }
              />
            ))}
        </Stack>
        {views.length > 0 && (
          <Card variant="outline" padding="md" aria-label="预览">
            <Stack gap={3}>
              <Row gap={2}>
                <Badge>预览</Badge>
                <Text as="span" size="sm" weight="bold">
                  {person} · {name.trim() || '赋能'}
                </Text>
              </Row>
              <LensStatements views={views} />
              <Text size="xs" tone="tertiary">
                根据{person}说过的话推测
              </Text>
            </Stack>
          </Card>
        )}
        {error && (
          <Text role="alert" size="sm" tone="danger">
            {error}
          </Text>
        )}
        <Row gap={2} justify="end">
          <Button variant="ghost" disabled={busy} onClick={onClose}>
            取消
          </Button>
          <Button loading={busy} disabled={!ready} onClick={() => void save()}>
            {lens
              ? '保存'
              : scope === 'team'
                ? '发布给全团队'
                : `发布给 ${twins.size} 人`}
          </Button>
        </Row>
      </Stack>
    </Dialog>
  );
}

/** An aspect that can be opened: how well the twin knows its best facet, and the tick. */
function AspectChoice({
  aspect,
  checked,
  stopped,
  onChange,
}: {
  aspect: Aspect;
  checked: boolean;
  stopped: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <Checkbox
      label={aspect.name}
      checked={checked}
      onChange={(event) => onChange(event.target.checked)}
    >
      <LevelDots level={aspect.level} label={aspect.label} />
      {aspect.checked && <Badge tone="success">✓</Badge>}
      {stopped && <Badge tone="warning">已停用</Badge>}
    </Checkbox>
  );
}
