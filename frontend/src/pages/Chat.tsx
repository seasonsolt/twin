import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useSearchParams } from 'react-router';
import { PanelLeft, SquarePen, X } from 'lucide-react';
import {
  ActionMenu,
  Badge,
  ChatSurface,
  Heading,
  IconButton,
  ResizeHandle,
  Segmented,
  Text,
  TextLink,
  useConfirm,
} from '../components/ui';
import { ChatStage } from '../features/chat/ChatStage';
import { ChatThread } from '../features/chat/ChatThread';
import { PersonPicker } from '../features/chat/PersonPicker';
import {
  SessionList,
  type Session,
  type SessionFilter,
} from '../features/chat/SessionList';
import { useAllSessions } from '../features/chat/useAllSessions';
import { useComposerLayout } from '../features/chat/useComposerLayout';
import { useConversation } from '../features/chat/useConversation';
import { usePlayback } from '../features/chat/usePlayback';
import { useWork } from '../features/work/useWork';
import { WorkThread } from '../features/work/WorkThread';
import { api } from '../lib/api';
import { twinMemberPath } from '../lib/members';
import { usePersonaId, usePersonaState } from '../lib/usePersonaState';
import { useMediaQuery, useMobile } from '../lib/useMobile';
import { useCanManage } from '../stores/access';
import { featureOn, useAuth } from '../stores/auth';
import { SHEET_WIDTH, useChatLayout } from '../stores/chatLayout';
import { usePersonas } from '../stores/personas';
import { useStatus } from '../stores/status';

type Mode = 'chat' | 'work';
const MODES = [
  { id: 'chat', label: '问答' },
  { id: 'work', label: '交代任务' },
] as const;
const byRecent = (a: Session, b: Session) =>
  Date.parse(b.updated_at) - Date.parse(a.updated_at);

/** What the list is narrowed to: everything, the tasks, one twin's, or the person's own assistant's. */
type Scope =
  | { kind: 'all' }
  | { kind: 'task' }
  | { kind: 'mine' }
  | { kind: 'person'; id: string };
// People named as chips above the list; the rest are found by choosing whom to talk to.
const PEOPLE_SHOWN = 5;

/**
 * The conversation page: every conversation and task of the signed-in person in one list (all of them, one twin's,
 * the tasks, or the pinned 我的分身, which only they have), and the one open. A message goes to the twin picked
 * beside the box, as a question or an instruction (``?mode=task``, hidden where work is switched off).
 */
export function Chat() {
  const personaId = usePersonaId();
  const { pathname, state, key } = useLocation();
  const [params, setParams] = useSearchParams();
  const active = pathname === '/chat';
  const confirm = useConfirm();
  // Work is the same page with another kind of message, so it is there unless an administrator switched it off.
  const workOn = useAuth(
    (auth) => auth.identity !== null && featureOn(auth.identity, 'work'),
  );
  const mode: Mode = workOn && params.get('mode') === 'task' ? 'work' : 'chat';
  const chat = useConversation(active);
  const work = useWork(workOn && active);
  // A question picked elsewhere (such as trying out a twin before saying it is all right) waits in the composer.
  const ask = (state as { ask?: unknown } | null)?.ask;
  const { setDraft } = chat;
  useEffect(() => {
    if (typeof ask === 'string') setDraft(ask);
  }, [ask, key, setDraft]);
  const mobile = useMobile();
  const wide = useMediaQuery('(min-width: 1280px)');
  const layout = useChatLayout();
  const sheetOpen = !mobile && (layout.sheet ?? wide);
  const stageOpen = layout.stage ?? false;
  const setChoice = layout.setChoice;
  const setStageOpen = (value: boolean) => setChoice('stage', value);
  const openStage = useCallback(() => setChoice('stage', true), [setChoice]);
  const [historyOpen, setHistoryOpen] = usePersonaState(false);
  const { refreshHistory } = chat;
  useEffect(() => {
    if (active) void refreshHistory();
  }, [active, refreshHistory]);
  useEffect(() => {
    if (!mobile) setHistoryOpen(false);
  }, [mobile, setHistoryOpen]);
  const historyTrigger = useRef<HTMLElement | null>(null);
  const openHistory = () => {
    historyTrigger.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    setHistoryOpen(true);
    void chat.refreshHistory();
    if (workOn) void work.reload();
  };
  const status = useStatus((state) => state.data);
  const persona = usePersonas((state) =>
    state.items.find((item) => item.id === state.id),
  );
  const name = status?.target_name || persona?.name || '本人';
  const canManage = persona?.can_manage ?? true;
  const runsTwins = useCanManage();
  const people = usePersonas((state) => state.items);
  const switchTo = usePersonas((state) => state.switchTo);
  const personName = useCallback(
    (id: string) => people.find((item) => item.id === id)?.name ?? '',
    [people],
  );
  // The conversation is the person's own with their assistant: it speaks to them, and they can try a question as a
  // colleague would be answered. The twin's own tier is the person's alone, so a conversation of the other tier with
  // it (from before, or before they said it is all right) is an ordinary one.
  const assistant =
    !!persona?.mine && !!persona.approved && chat.audience !== 'colleague';
  const [trialOn, setTrialOn] = usePersonaState(false);
  const [scope, setScope] = useState<Scope>({ kind: 'all' });
  const revision = [
    chat.history.map((row) => `${row.id}:${row.updated_at}:${row.title}`),
    (work.tasks ?? []).map((row) => `${row.task_id}:${row.updated_at}`),
  ]
    .map((rows) => rows.join())
    .join('|');
  const everything = useAllSessions(
    active,
    {
      mine: scope.kind === 'mine',
      with: scope.kind === 'person' ? scope.id : undefined,
    },
    revision,
  );
  const own = everything.data?.mine ?? null;
  const ownId = own?.persona_id ?? null;
  // Choosing another twin to write to leaves the assistant's list behind.
  useEffect(() => {
    if (scope.kind === 'mine' && ownId !== personaId) setScope({ kind: 'all' });
  }, [scope.kind, ownId, personaId]);
  // The people a conversation was had with, newest first, as the list's chips; kept while one is chosen.
  const [known, setKnown] = useState<string[]>([]);
  const dataRows = everything.data;
  useEffect(() => {
    if (!dataRows) return;
    const ids = [
      ...dataRows.conversations.map((row) => row.persona_id),
      ...dataRows.tasks.map((row) => row.persona_id),
    ];
    setKnown((previous) =>
      scope.kind === 'all'
        ? [...new Set(ids)]
        : [...new Set([...previous, ...ids])],
    );
  }, [dataRows, scope.kind]);
  // ``?with=`` opens the page on one twin: it is written to, and the list is narrowed to it; ``me`` is the person's
  // own twin (我的分身), once the twins are known. ``?open=`` with it opens that conversation of the twin (such as
  // what the assistant asked in the person's name).
  const withParam = params.get('with');
  const openParam = params.get('open');
  const [opening, setOpening] = useState<Session | null>(null);
  useEffect(() => {
    if (!withParam) return;
    if (withParam === 'me' && !people.length) return;
    const target =
      withParam === 'me' ? people.find((item) => item.mine)?.id : withParam;
    if (target) {
      setScope({ kind: 'person', id: target });
      void switchTo(target);
      if (openParam)
        setOpening({
          kind: 'chat',
          id: openParam,
          title: '',
          updated_at: '',
          personaId: target,
        });
    }
    setParams(
      (previous) => {
        const query = new URLSearchParams(previous);
        query.delete('with');
        query.delete('open');
        return query;
      },
      { replace: true },
    );
  }, [withParam, openParam, people, switchTo, setParams]);
  const playback = usePlayback({ active, chat, name, openStage });
  const { audio, capabilities, currentTurn, toggleReply, stopPlayback } =
    playback;
  const composerLayout = useComposerLayout(active);
  const { page } = composerLayout;

  const newConversation = () => {
    chat.clear();
    stopPlayback();
  };
  const setMode = (next: Mode, carryDraft = true) => {
    if (next === mode) return;
    // What was typed goes along when the person switches: the words are the same, only what they are for changes.
    if (carryDraft && next === 'work') {
      if (chat.draft) work.setDraft(chat.draft);
      chat.setDraft('');
    } else if (carryDraft) {
      if (work.draft) chat.setDraft(work.draft);
      work.setDraft('');
    }
    setParams(
      (previous) => {
        const query = new URLSearchParams(previous);
        if (next === 'work') query.set('mode', 'task');
        else query.delete('mode');
        return query;
      },
      { replace: true },
    );
  };

  const named = scope.kind === 'all' || scope.kind === 'task';
  const sessions = useMemo<Session[]>(() => {
    if (!dataRows) return [];
    const who = (id: string) =>
      named ? personName(id) || undefined : undefined;
    return [
      ...(scope.kind === 'task'
        ? []
        : dataRows.conversations.map((row): Session => ({
            kind: 'chat',
            id: row.id,
            title: row.title,
            updated_at: row.updated_at,
            preview: row.preview,
            tag:
              row.via === 'delegate'
                ? '助手代问'
                : row.delegated
                  ? `代问 ${row.delegated} 人`
                  : (row.handoff ?? undefined),
            who:
              row.via === 'delegate'
                ? personName(row.persona_id) || undefined
                : who(row.persona_id),
            personaId: row.persona_id,
            // What the assistant asked is listed apart, with the assistant's own conversations.
            section:
              scope.kind === 'mine' && row.via === 'delegate'
                ? '问同事'
                : undefined,
          }))),
      ...(workOn ? dataRows.tasks : []).map((row): Session => ({
        kind: 'task',
        id: row.task_id,
        title: row.title,
        updated_at: row.updated_at,
        running: row.status === 'running',
        who: who(row.persona_id),
        personaId: row.persona_id,
      })),
    ].sort(byRecent);
  }, [dataRows, scope.kind, named, personName, workOn]);
  const openId =
    mode === 'work'
      ? work.current
        ? { kind: 'task' as const, id: work.current }
        : null
      : chat.conversationId
        ? { kind: 'chat' as const, id: chat.conversationId }
        : null;
  const openHere = async (session: Session) => {
    if (session.kind === 'task') {
      work.setCurrent(session.id);
      setMode('work', false);
      return true;
    }
    const loaded = await chat.resume(session.id);
    if (loaded) {
      stopPlayback();
      setMode('chat', false);
    }
    return loaded;
  };
  // A row of another twin's: the page goes to that twin first, then opens it there.
  const openSession = async (session: Session) => {
    if (session.personaId && session.personaId !== personaId) {
      setOpening(session);
      void switchTo(session.personaId);
      return true;
    }
    return openHere(session);
  };
  // Opening it is done once, when its twin is the one in view, with what that twin's render has.
  const openNow = useRef(openHere);
  useEffect(() => {
    openNow.current = openHere;
  });
  useEffect(() => {
    if (!opening || !active || opening.personaId !== personaId) return;
    setOpening(null);
    void openNow.current(opening);
  }, [opening, active, personaId]);
  const foreign = (session: Session) =>
    !!session.personaId && session.personaId !== personaId;
  const remove = async (session: Session) => {
    if (!foreign(session)) {
      if (session.kind === 'task') {
        const row = work.tasks?.find((task) => task.task_id === session.id);
        if (row) await work.remove(row);
        return;
      }
      const ok = await confirm({
        title: '删除对话？',
        body: `“${session.title}”将被永久删除。`,
        confirmLabel: '删除',
        tone: 'danger',
      });
      if (!ok) return;
      await chat.remove(session.id);
      if (session.id === chat.conversationId) stopPlayback();
      return;
    }
    // Another twin's: the same, asked of that twin.
    const task = session.kind === 'task';
    const ok = await confirm({
      title: task ? '删除任务？' : '删除对话？',
      body: task
        ? `“${session.title}”和做出来的文件都会删掉，不能恢复。`
        : `“${session.title}”将被永久删除。`,
      confirmLabel: '删除',
      tone: 'danger',
    });
    if (!ok) return;
    await api(
      `/api/${task ? 'persona/work' : 'conversations'}/${encodeURIComponent(session.id)}`,
      {
        method: 'DELETE',
        headers: { 'X-Twin-Persona': session.personaId ?? personaId },
      },
    );
    void everything.reload();
  };
  const rename = async (session: Session, title: string) => {
    if (!foreign(session)) return chat.rename(session.id, title);
    await api(`/api/conversations/${encodeURIComponent(session.id)}`, {
      method: 'PATCH',
      json: { title },
      headers: { 'X-Twin-Persona': session.personaId ?? personaId },
    });
    void everything.reload();
  };
  const newSession = () => {
    if (mode === 'work') work.setCurrent(null);
    else newConversation();
  };
  const presence =
    mode !== 'chat'
      ? ''
      : audio.speaking || playback.videoPlaying
        ? '正在说话'
        : chat.busy && !chat.newest
          ? '正在思考'
          : '';
  const newLabel = mode === 'work' ? '新任务' : '新对话';
  const picker = <PersonPicker persona={persona} name={name} inline />;
  const filters: SessionFilter[] = [
    { id: 'all', label: '全部' },
    ...known
      .slice(0, PEOPLE_SHOWN)
      .filter((id) => id !== ownId && personName(id))
      .map((id) => ({ id, label: personName(id) })),
    ...(workOn ? [{ id: 'task', label: '任务' }] : []),
  ];
  const chosen =
    scope.kind === 'person'
      ? scope.id
      : scope.kind === 'mine'
        ? undefined
        : scope.kind;
  const list = (
    <SessionList
      open={active && historyOpen}
      onOpenChange={(value) =>
        mobile ? setHistoryOpen(value) : layout.setChoice('sheet', value)
      }
      sessions={sessions}
      current={openId}
      loading={everything.loading && !everything.data}
      error={everything.error || chat.historyError}
      hasMore={!!everything.data?.more && scope.kind !== 'task'}
      onMore={() => void everything.more()}
      onRetry={() => {
        void everything.reload();
        void chat.refreshHistory();
        if (workOn) void work.reload();
      }}
      onOpen={openSession}
      onNew={newSession}
      onRename={rename}
      onDelete={remove}
      name={name}
      inline={!mobile}
      presence={presence || undefined}
      filters={filters}
      filter={chosen}
      onFilter={(id) =>
        setScope(
          id === 'all' || id === 'task' ? { kind: id } : { kind: 'person', id },
        )
      }
      pinned={
        ownId
          ? {
              label: '我的分身',
              waiting: own?.pending,
              selected: scope.kind === 'mine',
              onSelect: () => {
                if (scope.kind === 'mine') {
                  setScope({ kind: 'all' });
                  return;
                }
                setScope({ kind: 'mine' });
                void switchTo(ownId);
              },
            }
          : undefined
      }
      busy={chat.loading}
      newLabel={newLabel}
      returnFocus={historyTrigger}
    />
  );
  const title =
    mode === 'work'
      ? work.current === null
        ? '新任务'
        : (work.task?.title ?? '')
      : (sessions.find(
          (row) => row.kind === 'chat' && row.id === chat.conversationId,
        )?.title ??
        chat.history.find((entry) => entry.id === chat.conversationId)?.title ??
        '新对话');
  const modeSwitch = workOn ? (
    <Segmented
      label="这条消息是"
      value={mode}
      options={MODES}
      onChange={setMode}
    />
  ) : undefined;
  const speakLast = () => {
    toggleReply(
      [...chat.turns].reverse().find((turn) => turn.reply?.reply.trim()),
    );
  };
  const more =
    mode === 'chat' ? (
      <ActionMenu
        label="更多：语音、形象"
        items={[
          {
            label: '语音',
            disabled:
              !capabilities?.available ||
              !chat.turns.some((turn) => turn.reply?.reply.trim()),
            onSelect: speakLast,
          },
          {
            label: stageOpen ? '收起形象' : '形象',
            onSelect: () => setStageOpen(!stageOpen),
          },
        ]}
      />
    ) : null;
  const empty =
    mode === 'work'
      ? work.current === null
      : !chat.turns.length && !chat.loading;
  return (
    <div
      ref={page}
      className="chat-page chat-redesign"
      data-sheet={sheetOpen}
      data-empty={empty}
    >
      <audio ref={audio.audioRef} preload="auto" className="hidden" />
      {sheetOpen && (
        <ChatSurface variant="sheet" width={layout.sheetWidth}>
          {list}
          <ResizeHandle
            label="调整对话列表宽度"
            value={layout.sheetWidth ?? SHEET_WIDTH.default}
            min={SHEET_WIDTH.min}
            max={SHEET_WIDTH.max}
            defaultValue={SHEET_WIDTH.default}
            onChange={layout.setSheetWidth}
          />
        </ChatSurface>
      )}
      {mobile && list}
      <ChatSurface
        variant="panel"
        className="flex min-h-0 min-w-0 flex-1 flex-col"
      >
        <header className="chat-topbar" aria-label={`${name}的聊天`}>
          {mobile ? (
            <>
              <IconButton label="对话列表" onClick={openHistory}>
                <PanelLeft size={20} aria-hidden />
              </IconButton>
              <div className="min-w-0 flex-1">
                <Heading size="section" truncate>
                  {assistant ? '我的分身' : name}
                </Heading>
                {(presence || assistant) && (
                  <Text size="xs" tone="tertiary">
                    {presence || '仅你可见'}
                  </Text>
                )}
              </div>
              {more}
              <IconButton label={newLabel} onClick={newSession}>
                <SquarePen size={20} aria-hidden />
              </IconButton>
            </>
          ) : (
            <>
              {!sheetOpen && (
                <IconButton
                  label="展开对话列表"
                  onClick={() => layout.setChoice('sheet', true)}
                >
                  <PanelLeft size={18} aria-hidden />
                </IconButton>
              )}
              {runsTwins ? (
                <TextLink to={twinMemberPath(personaId)} weight="medium">
                  {assistant ? '我的分身' : name}
                </TextLink>
              ) : (
                <Text as="span" weight="medium">
                  {name}
                </Text>
              )}
              {assistant && <Badge tone="info">仅你可见</Badge>}
              <Heading
                level={1}
                weight="medium"
                size="item"
                truncate
                className="min-w-0 flex-1"
              >
                {title}
              </Heading>
              {more}
            </>
          )}
        </header>
        <div className="chat-body flex min-h-0 flex-1">
          {mode === 'work' ? (
            <WorkThread
              active={active}
              work={work}
              name={name}
              persona={persona}
              layout={composerLayout}
              modeSwitch={modeSwitch}
              target={picker}
            />
          ) : (
            <ChatThread
              active={active}
              chat={chat}
              playback={playback}
              name={name}
              persona={persona}
              canManage={canManage}
              layout={composerLayout}
              modeSwitch={modeSwitch}
              target={picker}
              assistant={assistant}
              trial={
                assistant ? { on: trialOn, onChange: setTrialOn } : undefined
              }
            />
          )}
          {mode === 'chat' && stageOpen && (
            <ChatSurface
              variant="stage"
              role="complementary"
              aria-label={`${name}的形象`}
            >
              <IconButton
                label="关闭形象"
                className="stage-close"
                onClick={() => setStageOpen(false)}
              >
                <X size={18} aria-hidden />
              </IconButton>
              <ChatStage
                name={name}
                capabilities={capabilities}
                turn={currentTurn}
                videoState={
                  currentTurn
                    ? playback.video.videos[currentTurn.id]
                    : undefined
                }
                videoPlaying={active && playback.videoPlaying}
                voiceCaption={audio.caption}
                level={audio.level}
                speaking={audio.speaking}
                thinking={chat.busy && !chat.newest}
                onToggle={() =>
                  toggleReply(
                    currentTurn ??
                      [...chat.turns]
                        .reverse()
                        .find((turn) => turn.reply?.reply.trim()),
                    true,
                  )
                }
                onVideoPlaying={playback.setVideoPlaying}
                onVideoError={() => {
                  if (!playback.videoId) return;
                  playback.video.invalidate(playback.videoId);
                  playback.setVideoId('');
                  playback.setVideoPlaying(false);
                  if (currentTurn?.reply)
                    audio.toggle(currentTurn.id, currentTurn.reply, name);
                }}
                onClear={newConversation}
                onHistory={openHistory}
                panel
              />
            </ChatSurface>
          )}
        </div>
      </ChatSurface>
    </div>
  );
}
