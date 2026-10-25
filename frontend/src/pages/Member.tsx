import { useEffect, useState } from 'react';
import {
  Navigate,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router';
import {
  Badge,
  Button,
  Notice,
  Page,
  Row,
  Skeleton,
  Stack,
  Tabs,
  Text,
  TextLink,
  toast,
} from '../components/ui';
import { api } from '../lib/api';
import { useMobile } from '../lib/useMobile';
import { chatPath, memberPath, twinMemberPath } from '../lib/members';
import { usePersonaId, usePersonaState } from '../lib/usePersonaState';
import { useIdentity } from '../features/identity/useIdentity';
import { Away } from '../features/away/Away';
import { LensTab } from '../features/lens/LensTab';
import { useAway } from '../features/away/useAway';
import { PersonFace } from '../features/library/PersonFace';
import { looseState, TWIN_STATES, twinState } from '../features/library/Team';
import { MemberHeader } from '../features/members/MemberHeader';
import { NoTwinMember } from '../features/members/NoTwinMember';
import { useMemoryCount } from '../features/members/useMemoryCount';
import { AssetsTab } from '../features/profile/AssetsTab';
import { EditIdentityDialog } from '../features/profile/EditIdentityDialog';
import { MemoriesTab, type MemoryView } from '../features/profile/MemoriesTab';
import { OverviewTab } from '../features/profile/OverviewTab';
import { PersonaSettings } from '../features/profile/PersonaSettings';
import { Ledger } from './Ledger';
import type { Person } from './Recording';
import { useIsSelf } from '../stores/access';
import { featureOn, useAuth } from '../stores/auth';
import { awaitsApproval, usePersonas, type Persona } from '../stores/personas';
import { useStatus } from '../stores/status';
import { useTeam } from '../stores/team';
import { useWelcome } from '../stores/welcome';

type Section = 'overview' | 'memories' | 'away' | 'ledger' | 'lens' | 'assets';

/** One member who has a twin: who they are, what the twin knows of them, and (for the person themselves) what it
 * could not answer while they were away. Someone else's public twin shows no more than the way to talk to it. */
function TwinMember({ twin, person }: { twin: Persona; person?: Person }) {
  const identity = useIdentity(true);
  const navigate = useNavigate();
  const mobile = useMobile();
  const [params, setParams] = useSearchParams();
  const canManage = twin.can_manage !== false;
  const self = useIsSelf(twin);
  const ledgerOn = useAuth((state) => featureOn(state.identity, 'ledger'));
  const memories = useMemoryCount(twin.id, canManage);
  const memoryUpdating = useStatus((state) => state.data?.memory_updating);
  // Where the twin stands is said as the team table says it. A twin the page can be opened on is one that can be
  // talked to, so the kinds that are about not having one (own, elsewhere, none) say only whether it is being
  // rebuilt, as they did before.
  const found = person ? twinState(person) : looseState(twin);
  const standing =
    found === 'none' || found === 'own' || found === 'elsewhere'
      ? person?.updating || memoryUpdating
        ? 'updating'
        : 'ready'
      : found === 'ready' && memoryUpdating
        ? 'updating'
        : found;
  const away = useAway(self && canManage);
  const waiting = away.data?.pending;
  const available: Section[] = [
    'overview',
    'memories',
    ...(self ? (['away'] as const) : []),
    ...(ledgerOn ? (['ledger'] as const) : []),
    // Lending their judgement to colleagues is the person's alone to decide.
    ...(self ? (['lens'] as const) : []),
    'assets',
  ];
  // Older links name places that now live elsewhere: the graph is a view of the memories, and the questions the twin
  // could not answer are the person's own, under 你不在时.
  const requested = params.get('section') ?? params.get('tab') ?? '';
  const renamed: Record<string, Section> = {
    graph: 'memories',
    questions: self ? 'away' : 'overview',
    channels: 'overview',
  };
  const section: Section =
    available.find((id) => id === requested) ??
    renamed[requested] ??
    'overview';
  const asked = params.get('view');
  const view: MemoryView =
    requested === 'graph' || asked === 'graph'
      ? 'graph'
      : asked === 'answers' && self
        ? 'answers'
        : 'list';
  const [settings, setSettings] = useState<string | null>(null);
  const [editing, setEditing] = usePersonaState(false);
  // An old link to the channels opens them over the page, then reads as the page's own link, so closing the dialog
  // and going back and forward behave like any other dialog.
  useEffect(() => {
    if (requested !== 'channels') return;
    setSettings('channels');
    setParams({ section: 'overview' }, { replace: true });
  }, [requested, setParams]);
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [section]);
  const togglePublic = async () => {
    try {
      await api(`/api/personas/${encodeURIComponent(twin.id)}`, {
        method: 'PATCH',
        json: { public: !twin.public },
      });
      await usePersonas.getState().refresh();
    } catch (failure) {
      toast(failure instanceof Error ? failure.message : '操作失败', 'danger');
    }
  };
  const name = identity.data?.name || twin.name;
  const choose = (next: string) =>
    setParams(next === 'overview' ? {} : { section: next }, { replace: true });
  return (
    <div className="profile-page">
      <Page>
        <MemberHeader
          name={name}
          you={self}
          about={identity.data?.about}
          face={
            <PersonFace
              name={name}
              twin={twin}
              preset={
                identity.data?.avatar_preset ??
                identity.data?.avatar ??
                undefined
              }
            />
          }
          status={TWIN_STATES[standing]}
          badge={twin.public && canManage ? <Badge>公开</Badge> : undefined}
          menu={
            canManage
              ? [
                  { label: '编辑', onSelect: () => setEditing(true) },
                  { label: '接入', onSelect: () => setSettings('channels') },
                  { label: '别名', onSelect: () => setSettings('aliases') },
                  {
                    label: '外部服务',
                    onSelect: () => setSettings('services'),
                  },
                  {
                    label: twin.public ? '设为私有' : '设为公开',
                    onSelect: () => void togglePublic(),
                  },
                  ...(twin.is_default && !twin.retirable
                    ? []
                    : [
                        {
                          label: '删除分身',
                          danger: true,
                          onSelect: () => setSettings('delete'),
                        },
                      ]),
                ]
              : undefined
          }
          primary={{
            // Their own twin is their assistant, which only they have.
            label:
              twin.mine && twin.approved ? '问问我的分身' : `和${name}聊天`,
            onClick: () => navigate(chatPath(twin.id)),
          }}
        />
        {awaitsApproval(twin) && (
          // They left the twin step for later: until they say it is all right, colleagues cannot ask it, and
          // what they see here is the part colleagues would.
          <Notice
            tone="info"
            actions={
              <Button
                variant="secondary"
                onClick={() => useWelcome.getState().reopenClaim()}
              >
                去确认
              </Button>
            }
          >
            分身还没确认，同事问不到它。
          </Notice>
        )}
        {canManage && (
          <Tabs
            label="档案章节"
            scrollable={mobile}
            value={section}
            onValueChange={choose}
            items={[
              {
                value: 'overview',
                label: '档案',
                content: (
                  <Stack gap={4}>
                    <OverviewTab
                      ask={
                        // Someone looking after a twin made for a person can ask that person for more.
                        !self && twin.claim
                          ? {
                              name,
                              path: person
                                ? memberPath(person.id)
                                : twinMemberPath(twin.id),
                            }
                          : undefined
                      }
                    />
                  </Stack>
                ),
              },
              {
                value: 'memories',
                label: (
                  <Row gap={2} as="div">
                    记忆
                    {memories ? (
                      <Text as="span" size="sm" tone="inherit">
                        {memories}
                      </Text>
                    ) : null}
                  </Row>
                ),
                content: (
                  <MemoriesTab
                    identity={identity}
                    view={view}
                    answers={self}
                    onView={(next) =>
                      setParams(
                        next === 'list'
                          ? { section: 'memories' }
                          : { section: 'memories', view: next },
                        { replace: true },
                      )
                    }
                  />
                ),
              },
              ...(self
                ? [
                    {
                      value: 'away',
                      keep: true,
                      label: (
                        <Row gap={2} as="div">
                          你不在时
                          {waiting ? (
                            <Text as="span" size="sm" tone="inherit">
                              {waiting}
                            </Text>
                          ) : null}
                        </Row>
                      ),
                      content: <Away away={away} />,
                    },
                  ]
                : []),
              ...(ledgerOn
                ? [
                    {
                      value: 'ledger',
                      label: '承诺',
                      content: <Ledger />,
                    },
                  ]
                : []),
              ...(self
                ? [
                    {
                      value: 'lens',
                      label: '赋能',
                      content: <LensTab person={name} />,
                    },
                  ]
                : []),
              {
                value: 'assets',
                label: '形象和声音',
                content: <AssetsTab identity={identity} />,
              },
            ]}
          />
        )}
        {canManage && (
          <>
            <PersonaSettings
              section={settings}
              onSection={setSettings}
              name={name}
            />
            <EditIdentityDialog
              open={editing}
              onOpenChange={setEditing}
              identity={identity}
            />
          </>
        )}
      </Page>
    </div>
  );
}

/**
 * A member's page: ``/team/:id`` for someone found in the recordings (``people.id``), ``/team/twin/:twinId`` for a twin
 * no recording belongs to. The twin the page is about is switched to first, because everything under it (profile,
 * memories, ledger) is asked for the twin in view.
 */
export function Member() {
  const { id: personId, twinId: twinRoute } = useParams();
  const { search } = useLocation();
  const people = useTeam((state) => state.people);
  const twins = usePersonas((state) => state.items);
  const current = usePersonaId();
  const [listed, setListed] = useState(false);
  const [failed, setFailed] = useState('');
  // The roster has been asked for, whatever came of it: the address of a twin waits for it, to lead on to the person.
  const [asked, setAsked] = useState(false);
  useEffect(() => {
    let alive = true;
    void usePersonas
      .getState()
      .refresh()
      .catch(() => {})
      .finally(() => alive && setListed(true));
    return () => {
      alive = false;
    };
  }, []);
  useEffect(() => {
    if (!(personId || twinRoute) || people) return;
    let alive = true;
    void useTeam
      .getState()
      .refreshPeople()
      .catch((failure: unknown) => {
        // A twin's page does not stand on the roster: without it the twin is shown as it is.
        if (alive && personId)
          setFailed(
            failure instanceof Error ? failure.message : '无法加载成员',
          );
      })
      .finally(() => alive && setAsked(true));
    return () => {
      alive = false;
    };
  }, [personId, twinRoute, people]);
  const person = personId ? people?.find((p) => p.id === personId) : undefined;
  const twin = twins.find(
    (t) => t.id === (twinRoute ?? person?.persona_id ?? person?.talk),
  );
  // A twin that has a person in the team's roster is reached by the person: the twin's own address leads there.
  const ofTwin = twinRoute
    ? people?.find((p) => p.persona_id === twinRoute || p.talk === twinRoute)
    : undefined;
  const target = twin?.id;
  useEffect(() => {
    if (target && target !== current)
      void usePersonas.getState().switchTo(target);
  }, [target, current]);
  if (failed)
    return (
      <Page>
        <Text role="alert" tone="danger">
          {failed}
        </Text>
        <TextLink to="/team">回到团队</TextLink>
      </Page>
    );
  if (twinRoute) {
    if (!people && !asked) return <Loading />;
    // The tab asked for goes with it (the account's 你不在时 number leads to ``?section=away``).
    if (ofTwin)
      return <Navigate to={`${memberPath(ofTwin.id)}${search}`} replace />;
    if (!twin) return listed ? <Navigate to="/team" replace /> : <Loading />;
  } else if (!people) return <Loading />;
  else if (!person) return <Navigate to="/team" replace />;
  else if (!twin)
    return listed ? <NoTwinMember person={person} /> : <Loading />;
  // Until the switch has happened, the pages under it would ask for another twin.
  if (!twin || twin.id !== current) return <Loading />;
  return (
    <TwinMember
      key={twin.id}
      twin={twin}
      person={
        person ??
        people?.find((p) => p.persona_id === twin.id || p.talk === twin.id)
      }
    />
  );
}

function Loading() {
  return (
    <Page>
      <Skeleton className="h-40" />
    </Page>
  );
}
