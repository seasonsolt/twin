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
  type Voice,
} from '../features/library/review';
import {
  disownedPeople,
  inAll,
  namedPeople,
  similarPairs,
  unnamedPeople,
  type Paged,
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
// Which list of the queue each group of voices is.
const LIST: Record<'main' | Folded, Paged> = {
  main: 'voices',
  enough: 'enough',
  stranger: 'strangers',
};
// Rounded up to a whole page, so a run of answers waiting to be taken back asks the server again once a page.
const whole = (count: number) =>
  Math.ceil(count / VOICES_PER_PAGE) * VOICES_PER_PAGE;
const groupOf = (voice: Pick<Voice, 'enough' | 'stranger'>) =>
  voice.stranger ? 'stranger' : voice.enough ? 'enough' : 'main';
// Asked for more than has arrived yet: the next page waits for it, however far the owner scrolls.
const awaited = (asked: number, shown: number, all: number) =>
  asked > shown && shown < all;

/** Send the person to the people the library found, for them to recognise themselves by voice. */
function copyInvite() {
  const invite = `我们在用会议录音整理每个人的发言，为你建分身。打开这个链接，登录后录一句话，就能认出哪些是你说的：${window.location.origin}${basePath()}/`;
  void navigator.clipboard.writeText(invite).then(
    () => toast('邀请已复制，可以发给同事', 'success'),
    () => toast(invite, 'info', 15000),
  );
}

/** The rows of the list as they stood when the page was left for a recording (the page is gone by the time its
 * answer is back). */
let left: string[] = [];

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
  const [voicesShown, setVoicesShown] = useState(VOICES_PER_PAGE);
  const [pages, setPages] = useState<Partial<Record<Shown, number>>>({});
  // Voices answered here but not yet settled on the server, in each group, still come with the queue: while the
  // server has more, as many more are asked for to keep a page of open ones. Only ever more, so settling them (they
  // are gone from the queue) does not ask again.
  const [extra, setExtra] = useState<Record<'main' | Folded, number>>({
    main: 0,
    enough: 0,
    stranger: 0,
  });
  const data = useTeamData({
    version,
    onReload: reload,
    first: {
      voices: whole(voicesShown + extra.main),
      enough: whole((pages.enough ?? VOICES_PER_PAGE) + extra.enough),
      strangers: whole((pages.stranger ?? VOICES_PER_PAGE) + extra.stranger),
      items: pages.disputed ?? TASKS_PER_PAGE,
      unsorted: pages.unsorted ?? TASKS_PER_PAGE,
      suspects: pages.mixed ?? TASKS_PER_PAGE,
    },
  });
  const {
    people,
    waiting,
    voices,
    fragments,
    unsorted,
    suspects,
    heard,
    totals,
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
  // An answer told to the server after the page was left has no page to show it failed: it says so on its own.
  const told = (run: () => Promise<string>) => async () => {
    const failed = await run();
    if (failed && !here.current)
      toast(`刚才的答案没有记下：${failed}`, 'danger', 8000);
  };
  const confirm = useConfirm();
  const navigate = useNavigate();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const twins = usePersonas((state) => state.items);
  const [reviewing, setReviewing] = useState<SuspectSpeaker | null>(null);
  const [addressing, setAddressing] = useState<Person | null>(null);
  // Why the e-mail or employee number was not saved: the dialog stays open with it, and what was typed.
  const [claimError, setClaimError] = useState('');
  const address = (person: Person | null) => {
    setClaimError('');
    setAddressing(person);
  };
  // The row that takes the keyboard next, after one is settled.
  const [focusRow, setFocusRow] = useState<string | null>(null);
  // Voices answered here, for “3 / 69”; one settled in its recording and come back from is one more.
  const [answered, setAnswered] = useState<number>(
    () =>
      (location.state?.inboxAnswered ?? 0) +
      (location.state?.resolvedInboxTask &&
      categoryOf(location.state.resolvedInboxTask) === 'voice'
        ? 1
        : 0),
  );

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
  const loadedIn = (group: 'main' | Folded) =>
    voices.filter((voice) => groupOf(voice) === group);
  // How many voices of a group are still on the server, not loaded, and how long they speak.
  const unloaded = (group: 'main' | Folded) => {
    const loaded = loadedIn(group);
    const seconds = loaded.reduce((sum, voice) => sum + voice.seconds, 0);
    const total = totals?.[LIST[group]];
    return {
      count: Math.max(0, (total?.count ?? loaded.length) - loaded.length),
      seconds: Math.max(0, (total?.seconds ?? seconds) - seconds),
    };
  };
  const heldIn = (group: 'main' | Folded) =>
    voiced.filter((v) => !live(v.id) && groupOf(v) === group).length;
  const [heldMain, heldEnough, heldStranger] = [
    heldIn('main'),
    heldIn('enough'),
    heldIn('stranger'),
  ];
  const [moreMain, moreEnough, moreStranger] = [
    unloaded('main').count > 0,
    unloaded('enough').count > 0,
    unloaded('stranger').count > 0,
  ];
  useEffect(
    () =>
      setExtra((now) => {
        const next = {
          main: moreMain ? Math.max(now.main, heldMain) : now.main,
          enough: moreEnough ? Math.max(now.enough, heldEnough) : now.enough,
          stranger: moreStranger
            ? Math.max(now.stranger, heldStranger)
            : now.stranger,
        };
        return next.main === now.main &&
          next.enough === now.enough &&
          next.stranger === now.stranger
          ? now
          : next;
      }),
    [heldMain, heldEnough, heldStranger, moreMain, moreEnough, moreStranger],
  );
  // New people (all loaded with the people) among the voices: one ranked after the last voice loaded may yet be
  // passed by a voice still to load, so none is shown past that voice until the rest are.
  let lastLoaded = -1;
  voiced.forEach((v, i) => {
    if (v.kind === 'voice' && groupOf(v) === 'main') lastLoaded = i;
  });
  const reachable = unloaded('main').count
    ? voiced.filter((v, i) => v.kind === 'voice' || i < lastLoaded)
    : voiced;
  const open = reachable.filter((item) => live(item.id));
  const main = open.filter((v) => !v.enough && !v.stranger);
  // The rows of the list: an answer waiting to be taken back stays where its voice was, as what was done.
  const listed: VoiceItem[] = [];
  let seen = 0;
  for (const item of reachable) {
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
  // Every open voice of a group, those still on the server too.
  const mainCount =
    voiced.filter((v) => live(v.id) && groupOf(v) === 'main').length +
    unloaded('main').count;
  const enoughCount = enough.length + unloaded('enough').count;
  const strangerCount = strangers.length + unloaded('stranger').count;
  // How many of a kind are loaded: those still to load are asked for as the owner scrolls.
  const loaded: Partial<Record<Category, number>> = {
    mixed: suspects.length,
    unsorted: unsorted.length,
    disputed: waiting.length,
  };
  const counts: Record<Category, number> = {
    voice: mainCount + enoughCount + strangerCount,
    mixed: inAll({ totals }, 'suspects', suspects.length),
    unsorted: inAll({ totals }, 'unsorted', unsorted.length),
    failed: failed.length,
    similar: similar.length,
    disputed: inAll({ totals }, 'items', waiting.length),
    disowned: disowned.length,
    fragments: fragments.length && live('fragments') ? 1 : 0,
  };
  // The tab counts what the side bar does (``waitingCount``): voices surely heard enough already, or like ones the
  // owner could not name, stay listed, folded away, but are not counted.
  const shown: Record<Category, number> = { ...counts, voice: mainCount };
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

  // The rows the keyboard walks through, as they stand.
  const order = [...main.slice(0, voicesShown), ...enough, ...strangers].map(
    (item) => item.id,
  );
  // Where they stood when the page was left for a recording, for the keyboard to land after the one settled there.
  const standing = useRef(order);
  // Taken as the page opens: leaving it again (or a development double mount) writes the variable anew.
  const [stood] = useState(() => left);
  useEffect(() => {
    standing.current = order;
  });
  useEffect(
    () => () => {
      left = standing.current;
    },
    [],
  );
  // Back from settling a speaker in its recording: the kind it was part of, and the keyboard on the row after it.
  const returned: string | undefined = location.state?.resolvedInboxTask;
  useEffect(() => {
    if (!returned) return;
    const kind = categoryOf(returned);
    if (kind && params.get('cat') !== kind) go({ cat: kind });
  }, [returned, params, go]);
  useEffect(() => {
    if (!returned || !reviewReady || busy) return;
    const at = stood.indexOf(returned);
    const standingNow = (id: string) => id !== returned && order.includes(id);
    const next =
      at < 0
        ? undefined
        : (stood.slice(at + 1).find(standingNow) ??
          [...stood.slice(0, at)].reverse().find(standingNow));
    setFocusRow(
      category?.id === 'voice' ? (next ?? main[0]?.id ?? null) : null,
    );

    void navigate(`${location.pathname}${location.search}`, {
      replace: true,
      state: null,
    });
  }, [
    returned,
    reviewReady,
    busy,
    category,
    main,
    order,
    stood,
    navigate,
    location,
  ]);

  // The keyboard goes where the settled row was, so a run of answers is a run of keys.
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
    deferred.defer(
      item.id,
      label,
      told(() =>
        item.kind === 'voice'
          ? data
              .decideVoice(item.voice.members, decisionOf(how), false)
              .then((failed) => {
                // Given to the unnamed person it is most like, who is called by the name typed from now on.
                const unnamed =
                  how.to === 'name' &&
                  people?.find((p) => p.id === how.person.id);
                return failed || !unnamed
                  ? failed
                  : data.rename(unnamed, how.name, false);
              })
          : how.to === 'person'
            ? data.resolve(item.person, how.person, false)
            : how.to === 'new'
              ? data.rename(item.person, how.name, false)
              : data.resolve(item.person, null, false),
      ),
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
    deferred.defer(
      'fragments',
      `已归给${person.name}`,
      told(() =>
        data.decideVoice(
          members,
          { action: 'confirm', person_id: person.person_id, sample: false },
          false,
        ),
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
        <VoiceRow
          key={item.id}
          item={item}
          people={people ?? []}
          known={known}
          onAnswer={answer}
        />
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
  const more = (group: Category, total: number) => {
    const shown = Math.min(page(group), loaded[group] ?? total);
    return (
      <LoadMore
        shown={shown}
        total={total}
        label={`再显示 ${Math.min(TASKS_PER_PAGE, total - shown)} 个`}
        disabled={awaited(page(group), loaded[group] ?? total, total)}
        onLoadMore={() => showMore(group)}
      />
    );
  };
  const folded = (
    summary: string,
    rows: VoiceItem[],
    all: number,
    group: Folded,
  ) =>
    all > 0 && (
      <Disclosure
        summary={summary}
        variant="plain"
        defaultOpen={mainCount === 0}
      >
        <Stack as="ul" gap={0}>
          {voiceRows(rows.slice(0, pages[group] ?? VOICES_PER_PAGE))}
        </Stack>
        <LoadMore
          shown={Math.min(rows.length, pages[group] ?? VOICES_PER_PAGE)}
          total={all}
          label="继续显示声音"
          disabled={awaited(pages[group] ?? VOICES_PER_PAGE, rows.length, all)}
          onLoadMore={() =>
            setPages((current) => ({
              ...current,
              [group]: (current[group] ?? VOICES_PER_PAGE) + VOICES_PER_PAGE,
            }))
          }
        />
      </Disclosure>
    );

  // The open voices of the list's first group shown, and those after them, on the server too.
  const shownMain = listed.filter((item) => live(item.id)).length;
  const later = {
    count: mainCount - shownMain,
    seconds:
      main
        .filter((item) => !listed.includes(item))
        .reduce((total, row) => total + row.seconds, 0) +
      voiced
        .filter((v) => live(v.id) && !reachable.includes(v))
        .reduce((total, row) => total + row.seconds, 0) +
      unloaded('main').seconds,
  };

  let body = null;
  const id = category?.id;
  if (id === 'voice')
    body = (
      <Stack gap={4}>
        <Stack as="ul" gap={0} aria-label="新的声音">
          {settledRows('voice', listed)}
          {voiceRows(listed)}
        </Stack>
        {later.count > 0 && (
          <LoadMore
            shown={shownMain}
            total={mainCount}
            label={`再显示 ${Math.min(VOICES_PER_PAGE, later.count)} 个`}
            description={`还有 ${later.count} 个说得更少（共 ${span(later.seconds)}）`}
            disabled={awaited(voicesShown, shownMain, mainCount)}
            onLoadMore={() => setVoicesShown((n) => n + VOICES_PER_PAGE)}
          />
        )}
        {folded(`已够建分身 ${enoughCount}`, enough, enoughCount, 'enough')}
        {folded(
          `${strangerCount} 个像你标过不认识的`,
          strangers,
          strangerCount,
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
        {more('mixed', counts.mixed)}
      </Stack>
    );
  else if (id === 'unsorted')
    body = (
      <Stack gap={4}>
        <UnsortedList
          items={unsorted.slice(0, page('unsorted'))}
          recordings={recordings}
        />
        {more('unsorted', counts.unsorted)}
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
              told(() => data.merge(a, b, false)),
            )
          }
          onApart={(a, b) =>
            deferred.defer(
              `similar-${a.id}-${b.id}`,
              `${a.name}和${b.name}不是同一个人`,
              told(() => data.apart(a, b, false)),
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
        {more('disputed', counts.disputed)}
      </Stack>
    );
  else if (id === 'disowned')
    body = (
      <Stack gap={4}>
        <DisownedList
          people={disowned.slice(0, page('disowned'))}
          twinOf={twinOf}
          busy={busy}
          onAddress={address}
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
              deferred.defer(
                'fragments',
                '已放一边',
                told(() =>
                  data.decideVoice(fragments, { action: 'unknown' }, false),
                ),
              )
            }
          />
        )}
      </Stack>
    );

  const lastVoice = [...deferred.waiting]
    .reverse()
    .find(({ id: task }) => categoryOf(task) === 'voice');
  const total = answered + counts.voice;
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
          answered={answered}
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
                    {shown[c.id]}
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
        error={claimError}
        onClose={() => address(null)}
        onSave={(claim) => {
          if (!addressing) return;
          setClaimError('');
          void data.saveClaim(addressing, claim).then((failed) => {
            if (failed) setClaimError(failed);
            else address(null);
          });
        }}
      />
      <MixedSpeaker
        suspect={reviewing}
        onClose={() => setReviewing(null)}
        onChanged={load}
      />
    </Page>
  );
}
