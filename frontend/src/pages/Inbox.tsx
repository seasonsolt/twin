import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router';
import {
  Button,
  Disclosure,
  LoadMore,
  Meter,
  Notice,
  Page,
  Row,
  Segmented,
  Stack,
  Tabs,
  Text,
  toast,
  useConfirm,
} from '../components/ui';
import { basePath } from '../lib/base';
import { usePolling } from '../lib/usePolling';
import { usePersonas } from '../stores/personas';
import { useTeam } from '../stores/team';
import {
  MixedSpeaker,
  type SuspectSpeaker,
} from '../features/library/MixedSpeaker';
import { WorkClaim } from '../features/library/WorkClaim';
import {
  CATEGORIES,
  categoryOf,
  span,
  type Category,
  type Fragment,
} from '../features/library/review';
import {
  disownedPeople,
  namedPeople,
  similarPairs,
  unnamedPeople,
} from '../features/library/teamCounts';
import { useLibraryFeed } from '../features/library/useLibraryFeed';
import { useTeamData } from '../features/library/useTeamData';
import { useUploads } from '../features/library/useUploads';
import type { Person } from './Recording';
import { InboxFocus } from '../features/inbox/InboxFocus';
import {
  DisownedList,
  DisputedList,
  FailedList,
  FragmentsRow,
  MixedList,
  SimilarList,
  UnsortedList,
} from '../features/inbox/OtherRows';
import { SettledRow, VoiceRow, rowId } from '../features/inbox/VoiceRows';
import { useDeferred } from '../features/inbox/useDeferred';
import {
  decisionOf,
  labelOf,
  type Answer,
  type VoiceItem,
} from '../features/inbox/voice';

// New voices shown at first, and each time more are asked for.
const VOICES_PER_PAGE = 20;
const TASKS_PER_PAGE = 10;
type Folded = 'enough' | 'stranger';
type Shown = Category | Folded;

/** Send the person to the people the library found, for them to recognise themselves by voice. */
function copyInvite() {
  const invite = `我们在用会议录音整理每个人的发言，为你建分身。打开这个链接，登录后录一句话，就能认出哪些是你说的：${window.location.origin}${basePath()}/`;
  void navigator.clipboard.writeText(invite).then(
    () => toast('邀请已复制，可以发给同事', 'success'),
    () => toast(invite, 'info', 15000),
  );
}

/**
 * What waits for the owner (``/inbox``): the new voices of the recordings, and the other things the team's library
 * cannot settle by itself, a kind of thing at a time. A list, or the new voices one by one with the keyboard. What
 * is settled here is told to the server a few seconds later, so it can be taken back (``useDeferred``).
 */
export function Inbox() {
  const {
    library,
    error: libraryError,
    version,
    load: reload,
    poll,
  } = useLibraryFeed();
  const { uploading } = useUploads(() => void reload());
  const data = useTeamData({ version, onReload: reload });
  const {
    people,
    waiting,
    voices,
    fragments,
    unsorted,
    suspects,
    heard,
    reviewError,
    reviewReady,
    error,
    busy,
    load,
  } = data;
  const recordings = library?.recordings ?? [];
  usePolling(poll, uploading || library?.pending ? 3000 : 0);
  // Answers told to the server after the page was left: the page that is open then follows the library again.
  const here = useRef(true);
  useEffect(() => {
    here.current = true;
    return () => {
      here.current = false;
    };
  }, []);
  const settle = useCallback(async () => {
    await load();
    if (!here.current)
      useTeam.setState((state) => ({ version: state.version + 1 }));
  }, [load]);
  const deferred = useDeferred({ settle });
  const confirm = useConfirm();
  const navigate = useNavigate();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const twins = usePersonas((state) => state.items);
  const [reviewing, setReviewing] = useState<SuspectSpeaker | null>(null);
  const [addressing, setAddressing] = useState<Person | null>(null);
  const [voicesShown, setVoicesShown] = useState(VOICES_PER_PAGE);
  const [pages, setPages] = useState<Partial<Record<Shown, number>>>({});
  // The row that takes the keyboard next, after one is settled.
  const [focusRow, setFocusRow] = useState<string | null>(null);
  // Voices answered here, for “3 / 69”.
  const [answered, setAnswered] = useState(0);

  const named = useMemo(() => namedPeople(people ?? []), [people]);
  const known = useMemo(() => (people ?? []).filter((p) => !p.auto), [people]);
  const failed = recordings.filter((r) => r.status === 'failed');
  const similar = similarPairs(people ?? []).filter(
    ([a, b]) => !deferred.has(`similar-${a.id}-${b.id}`),
  );
  const disowned = disownedPeople(named, twins);
  const twinOf = (person: Person) =>
    twins.find((t) => t.id === person.persona_id);
  const live = (id: string) => !deferred.has(id);

  // Whoever speaks longest first, a new person or a voice alike: settling them teaches a twin the most.
  const voiced: VoiceItem[] = [
    ...unnamedPeople(people ?? []).map((person): VoiceItem => ({
      kind: 'person',
      id: `person-${person.id}`,
      seconds: person.seconds,
      recordings: person.speakers,
      enough: false,
      stranger: false,
      person,
    })),
    ...voices.map((voice): VoiceItem => ({
      kind: 'voice',
      id: `voice-${voice.id}`,
      seconds: voice.seconds,
      recordings: new Set(voice.members.map((m) => m.recording_id)).size,
      enough: Boolean(voice.enough),
      stranger: Boolean(voice.stranger),
      voice,
    })),
  ].sort(
    // Whoever a twin still lacks first, then the voice heard in the most recordings (settled, it tells the others
    // there apart) and the longest; voices like one already marked 不认识 wait last.
    (a, b) =>
      Number(a.stranger) - Number(b.stranger) ||
      Number(a.enough) - Number(b.enough) ||
      b.recordings - a.recordings ||
      b.seconds - a.seconds,
  );
  const open = voiced.filter((item) => live(item.id));
  const main = open.filter((v) => !v.enough && !v.stranger);
  // The rows of the list: an answer waiting to be taken back stays where its voice was, as what was done.
  const listed: VoiceItem[] = [];
  let seen = 0;
  for (const item of voiced) {
    if (item.enough || item.stranger) continue;
    if (live(item.id)) {
      if (seen >= voicesShown) break;
      seen += 1;
    } else if (!deferred.held(item.id)) continue;
    listed.push(item);
  }
  const enough = open.filter((v) => v.enough && !v.stranger);
  const strangers = open.filter((v) => v.stranger);
  const settledHere = (category: Category) =>
    deferred.waiting.filter(({ id }) => categoryOf(id) === category).length;
  const counts: Record<Category, number> = {
    voice: open.length,
    mixed: suspects.length,
    unsorted: unsorted.length,
    failed: failed.length,
    similar: similar.length,
    disputed: waiting.length,
    disowned: disowned.length,
    fragments: fragments.length && live('fragments') ? 1 : 0,
  };
  // A kind stays in the tabs while a row of it waits to be taken back.
  const present = CATEGORIES.filter(
    (c) => counts[c.id] > 0 || settledHere(c.id) > 0,
  );
  const view = params.get('view') === 'focus' ? 'focus' : 'list';
  const requested = params.get('cat');
  const category =
    present.find((c) => c.id === requested) ??
    (view === 'focus' ? present.find((c) => c.id === 'voice') : undefined) ??
    present[0];
  const go = useCallback(
    (change: Record<string, string | null>) =>
      setParams(
        (current) => {
          const next = new URLSearchParams(current);
          for (const [key, value] of Object.entries(change))
            if (value === null) next.delete(key);
            else next.set(key, value);
          return next;
        },
        { replace: true },
      ),
    [setParams],
  );

  // Back from settling a speaker in its recording: the kind it was part of, and the keyboard in its first row.
  const returned: string | undefined = location.state?.resolvedInboxTask;
  useEffect(() => {
    if (!returned) return;
    const kind = categoryOf(returned);
    if (kind && params.get('cat') !== kind) go({ cat: kind });
  }, [returned, params, go]);
  useEffect(() => {
    if (!returned || !reviewReady || busy) return;
    setFocusRow(category?.id === 'voice' ? (main[0]?.id ?? null) : null);
    void navigate(`${location.pathname}${location.search}`, {
      replace: true,
      state: null,
    });
  }, [returned, reviewReady, busy, category, main, navigate, location]);

  // The keyboard goes where the settled row was, so a run of answers is a run of keys.
  const order = [...main.slice(0, voicesShown), ...enough, ...strangers].map(
    (item) => item.id,
  );
  useEffect(() => {
    if (!focusRow) return;
    const row = document.getElementById(rowId(focusRow));
    // The answers first (a name's button, or the field for one), the row's other controls after.
    const target =
      row?.querySelector<HTMLElement>(
        '[role="group"] button:not(:disabled), [role="group"] input',
      ) ?? row?.querySelector<HTMLElement>('button:not(:disabled), input');
    target?.focus();
    setFocusRow(null);
  }, [focusRow]);

  const answer = (item: VoiceItem, how: Answer) => {
    const label = labelOf(how);
    deferred.defer(item.id, label, () =>
      item.kind === 'voice'
        ? data.decideVoice(item.voice.members, decisionOf(how), false)
        : how.to === 'person'
          ? data.resolve(item.person, how.person, false)
          : how.to === 'new'
            ? data.rename(item.person, how.name, false)
            : data.resolve(item.person, null, false),
    );
    setAnswered((n) => n + 1);
    const index = order.indexOf(item.id);
    setFocusRow(
      order.slice(index + 1).find((id) => id !== item.id && live(id)) ??
        [...order.slice(0, index)].reverse().find(live) ??
        null,
    );
  };
  const undo = (id: string) => {
    deferred.undo(id);
    if (categoryOf(id) === 'voice') setAnswered((n) => Math.max(0, n - 1));
    setFocusRow(id);
  };
  const giveFragments = (
    person: { person_id: string; name: string },
    members: Fragment[],
  ) =>
    deferred.defer('fragments', `已归给${person.name}`, () =>
      data.decideVoice(
        members,
        { action: 'confirm', person_id: person.person_id, sample: false },
        false,
      ),
    );
  const removeRecording = async (recording: (typeof failed)[number]) => {
    if (
      await confirm({
        title: `删除「${recording.filename}」？`,
        body: '转写结果和试听文件会一起删除，不能恢复',
        confirmLabel: '删除录音',
        tone: 'danger',
      })
    )
      await data.removeRecording(recording);
  };

  const voiceRows = (items: VoiceItem[]) =>
    items.map((item) =>
      deferred.held(item.id) ? (
        <SettledRow
          key={item.id}
          id={item.id}
          label={deferred.labelOf(item.id)}
          meta={`${item.recordings} 段`}
          onUndo={() => undo(item.id)}
        />
      ) : (
        <VoiceRow key={item.id} item={item} known={known} onAnswer={answer} />
      ),
    );
  // Rows of a kind that wait to be taken back, apart from those listed in their own place.
  const settledRows = (kind: Category, inPlace: VoiceItem[] = []) =>
    deferred.waiting
      .filter(
        ({ id }) =>
          categoryOf(id) === kind && !inPlace.some((item) => item.id === id),
      )
      .map(({ id, label }) => (
        <SettledRow key={id} id={id} label={label} onUndo={() => undo(id)} />
      ));
  const showMore = (group: Shown) =>
    setPages((current) => ({
      ...current,
      [group]: (current[group] ?? TASKS_PER_PAGE) + TASKS_PER_PAGE,
    }));
  const page = (group: Shown) => pages[group] ?? TASKS_PER_PAGE;
  const more = (group: Category, total: number) => (
    <LoadMore
      shown={Math.min(page(group), total)}
      total={total}
      label={`再显示 ${Math.min(TASKS_PER_PAGE, total - page(group))} 个`}
      onLoadMore={() => showMore(group)}
    />
  );
  const folded = (summary: string, rows: VoiceItem[], group: Folded) =>
    rows.length > 0 && (
      <Disclosure
        summary={summary}
        variant="plain"
        defaultOpen={main.length === 0}
      >
        <Stack as="ul" gap={0}>
          {voiceRows(rows.slice(0, pages[group] ?? VOICES_PER_PAGE))}
        </Stack>
        <LoadMore
          shown={Math.min(rows.length, pages[group] ?? VOICES_PER_PAGE)}
          total={rows.length}
          label="继续显示声音"
          onLoadMore={() =>
            setPages((current) => ({
              ...current,
              [group]: (current[group] ?? VOICES_PER_PAGE) + VOICES_PER_PAGE,
            }))
          }
        />
      </Disclosure>
    );

  let body = null;
  const id = category?.id;
  if (id === 'voice')
    body = (
      <Stack gap={4}>
        <Stack as="ul" gap={0} aria-label="新的声音">
          {settledRows('voice', listed)}
          {voiceRows(listed)}
        </Stack>
        {main.length > voicesShown && (
          <LoadMore
            shown={voicesShown}
            total={main.length}
            label={`再显示 ${Math.min(VOICES_PER_PAGE, main.length - voicesShown)} 个`}
            description={`还有 ${main.length - voicesShown} 个说得更少（共 ${span(main.slice(voicesShown).reduce((total, row) => total + row.seconds, 0))}）`}
            onLoadMore={() => setVoicesShown((n) => n + VOICES_PER_PAGE)}
          />
        )}
        {folded(`${enough.length} 个像已经够建分身的人`, enough, 'enough')}
        {folded(
          `${strangers.length} 个像你标过不认识的`,
          strangers,
          'stranger',
        )}
        <Row gap={2} wrap>
          <Text size="sm" tone="secondary">
            认不出的人，请本人来认
          </Text>
          <Button type="button" variant="ghost" size="sm" onClick={copyInvite}>
            复制邀请
          </Button>
        </Row>
      </Stack>
    );
  else if (id === 'mixed')
    body = (
      <Stack gap={4}>
        <MixedList
          suspects={suspects.slice(0, page('mixed'))}
          busy={busy}
          onReview={setReviewing}
        />
        {more('mixed', suspects.length)}
      </Stack>
    );
  else if (id === 'unsorted')
    body = (
      <Stack gap={4}>
        <UnsortedList items={unsorted.slice(0, page('unsorted'))} />
        {more('unsorted', unsorted.length)}
      </Stack>
    );
  else if (id === 'failed')
    body = (
      <Stack gap={4}>
        {failed.length > 1 && (
          <Row justify="end">
            <Button
              variant="secondary"
              size="sm"
              disabled={busy}
              onClick={() => void data.retryAll(failed)}
            >
              全部重试
            </Button>
          </Row>
        )}
        <FailedList
          recordings={failed.slice(0, page('failed'))}
          busy={busy}
          onRetry={(r) => void data.retry(r)}
          onRemove={(r) => void removeRecording(r)}
        />
        {more('failed', failed.length)}
      </Stack>
    );
  else if (id === 'similar')
    body = (
      <Stack gap={4}>
        <Stack as="ul" gap={0}>
          {settledRows('similar')}
        </Stack>
        <SimilarList
          pairs={similar.slice(0, page('similar'))}
          onMerge={(a, b) =>
            deferred.defer(
              `similar-${a.id}-${b.id}`,
              `已合并${a.name}和${b.name}`,
              () => data.merge(a, b, false),
            )
          }
          onApart={(a, b) =>
            deferred.defer(
              `similar-${a.id}-${b.id}`,
              `${a.name}和${b.name}不是同一个人`,
              () => data.apart(a, b, false),
            )
          }
        />
        {more('similar', similar.length)}
      </Stack>
    );
  else if (id === 'disputed')
    body = (
      <Stack gap={4}>
        <DisputedList items={waiting.slice(0, page('disputed'))} />
        {more('disputed', waiting.length)}
      </Stack>
    );
  else if (id === 'disowned')
    body = (
      <Stack gap={4}>
        <DisownedList
          people={disowned.slice(0, page('disowned'))}
          twinOf={twinOf}
          busy={busy}
          onAddress={setAddressing}
        />
        {more('disowned', disowned.length)}
      </Stack>
    );
  else if (id === 'fragments')
    body = (
      <Stack gap={0}>
        <Stack as="ul" gap={0}>
          {settledRows('fragments')}
        </Stack>
        {live('fragments') && fragments.length > 0 && (
          <FragmentsRow
            fragments={fragments}
            onGive={giveFragments}
            onAside={() =>
              deferred.defer('fragments', '已放一边', () =>
                data.decideVoice(fragments, { action: 'unknown' }, false),
              )
            }
          />
        )}
      </Stack>
    );

  const lastVoice = [...deferred.waiting]
    .reverse()
    .find(({ id: task }) => categoryOf(task) === 'voice');
  const total = answered + open.length;
  const heardShare =
    heard && heard.total > 0
      ? Math.round((heard.settled / heard.total) * 100)
      : null;
  const focusing = view === 'focus';

  return (
    <Page
      stackHeaderOnMobile
      title="待处理"
      titleSize="display"
      actions={
        reviewReady && present.length > 0 ? (
          <Row gap={4}>
            {focusing ? (
              <Row gap={2}>
                <Text
                  as="span"
                  size="sm"
                  aria-label={`第 ${Math.min(answered + 1, Math.max(total, 1))} 个，共 ${total} 个`}
                >
                  {Math.min(answered + 1, Math.max(total, 1))} / {total}
                </Text>
                <div className="w-32">
                  <Meter
                    size="sm"
                    hideLabel
                    label={`已处理 ${answered} / ${total}`}
                    value={answered}
                    max={Math.max(total, 1)}
                  />
                </div>
              </Row>
            ) : (
              heardShare !== null && (
                <Row gap={2} title="已知是谁说的发言占比">
                  <div className="w-32">
                    <Meter
                      size="sm"
                      hideLabel
                      label="已认出的发言"
                      value={heard?.settled ?? 0}
                      max={heard?.total ?? 1}
                    />
                  </div>
                  <Text as="span" size="sm">
                    {heardShare}%
                  </Text>
                </Row>
              )
            )}
            <Segmented
              label="显示方式"
              value={view}
              options={[
                { id: 'list', label: '列表' },
                { id: 'focus', label: '逐个听' },
              ]}
              onChange={(next) =>
                go(
                  next === 'focus'
                    ? { view: 'focus', cat: 'voice' }
                    : { view: null },
                )
              }
            />
          </Row>
        ) : undefined
      }
    >
      {(error || libraryError) && (
        <Text role="alert" tone="danger">
          {error || libraryError}
        </Text>
      )}
      {reviewError ? (
        <Notice
          tone="danger"
          actions={
            <Button variant="secondary" onClick={() => void load()}>
              重试
            </Button>
          }
        >
          <Text role="alert" tone="inherit">
            {reviewError}
          </Text>
        </Notice>
      ) : !reviewReady ? (
        <Text role="status" tone="secondary">
          正在加载待处理事项…
        </Text>
      ) : !category ? (
        <Text tone="secondary">现在没有需要你处理的事。</Text>
      ) : focusing ? (
        <InboxFocus
          items={open}
          people={people ?? []}
          last={lastVoice}
          onAnswer={answer}
          onUndo={undo}
          onList={() => go({ view: null })}
        />
      ) : (
        <Stack gap={4}>
          <Tabs
            variant="filters"
            label="类别"
            value={category.id}
            onValueChange={(value) => go({ cat: value })}
            items={present.map((c) => ({
              value: c.id,
              label: (
                <Row gap={2} as="div" title={c.help}>
                  {c.label}
                  <Text as="span" size="sm" tone="inherit">
                    {counts[c.id]}
                  </Text>
                </Row>
              ),
            }))}
          />
          {body}
        </Stack>
      )}
      <WorkClaim
        person={addressing}
        twin={twins.find((t) => t.id === addressing?.persona_id)}
        busy={busy}
        onClose={() => setAddressing(null)}
        onSave={(claim) =>
          addressing &&
          void data.saveClaim(addressing, claim).then(() => setAddressing(null))
        }
      />
      <MixedSpeaker
        suspect={reviewing}
        onClose={() => setReviewing(null)}
        onChanged={load}
      />
    </Page>
  );
}
