// What waits for the owner in the team's review queue (``/api/library/review``), and how it is told apart: the
// shapes the server sends, the kinds of thing, and the words for them.
import type { SuspectSpeaker } from './MixedSpeaker';
import type { Speaker } from '../../pages/Recording';
import type { ReviewTotals } from './teamCounts';

export interface Waiting extends Speaker {
  recording_id: string;
  filename: string;
}

/** One undecided speaker of a voice heard across recordings. */
export interface VoiceMember {
  recording_id: string;
  filename: string;
  transcript_id: string;
  speaker_id: string;
  seconds: number;
}

/** A fragment, with the person its voice sounds like, if anyone. */
export interface Fragment extends VoiceMember {
  like?: { person_id: string; name: string } | null;
}

/** Undecided speakers of several recordings who sound like one person, longest first (``Team.voices``). */
export interface Voice {
  id: string;
  members: VoiceMember[];
  seconds: number;
  candidates: Speaker['candidates'];
  near: boolean;
  // Sounds like a voice the owner already said is nobody they know.
  stranger?: boolean;
  // What the meeting calls the speakers, and what was said that names them.
  called?: string | null;
  quote?: string;
  // The leading candidate, surely the one, already heard this long; enough for a twin, so the voice waits behind.
  had?: number;
  enough?: boolean;
  // 'mid': voice alone is not sure enough to decide, but the leading candidate is far enough ahead to be offered
  // for one key (``team.tier``).
  tier?: 'mid' | 'low';
}

/** A recording whose undecided speakers have no voiceprint to group by: settled in the recording itself. */
export interface Unsorted {
  recording_id: string;
  filename: string;
  speakers: number;
  total: number;
}

export interface Review {
  items: Waiting[];
  voices: Voice[];
  fragments: Fragment[];
  unsorted: Unsorted[];
  // Confirmed speakers some of whose speech sounds like someone else (``media.review``).
  suspects?: SuspectSpeaker[];
  // How long people speak in these recordings, and how much of it is settled.
  heard?: { settled: number; total: number };
  // How many each paged list holds in all (``reviewPath``).
  totals?: ReviewTotals;
}

/** What settling a voice tells the server: who it is, or that nobody known speaks there. */
export type VoiceDecision =
  | { action: 'confirm'; person_id: string; sample?: false }
  | { action: 'confirm'; new_person: string }
  | { action: 'unknown' }
  | { action: 'mixed' };

/** The kinds of thing waiting for the owner. */
export type Category =
  | 'voice'
  | 'mixed'
  | 'unsorted'
  | 'failed'
  | 'similar'
  | 'disputed'
  | 'disowned'
  | 'fragments';

/** Which kind a task belongs to, from its id (the id a recording page hands back once it is settled). */
export const categoryOf = (task: string): Category | undefined =>
  (
    [
      ['person-', 'voice'],
      ['voice-', 'voice'],
      ['mixed-', 'mixed'],
      ['unsorted-', 'unsorted'],
      ['failed-', 'failed'],
      ['similar-', 'similar'],
      ['speaker-', 'disputed'],
      ['disowned-', 'disowned'],
      ['fragments', 'fragments'],
    ] as const
  ).find(([prefix]) => task.startsWith(prefix))?.[1];

export const CATEGORIES: {
  id: Category;
  label: string;
  tone: 'warning' | 'danger' | 'info';
  help: string;
}[] = [
  {
    id: 'voice',
    label: '新的声音',
    tone: 'warning',
    help: '说得最多的在前',
  },
  {
    id: 'unsorted',
    label: '还没认人',
    tone: 'warning',
    help: '这些录音的说话人没有声纹可比，要在录音里逐个确认',
  },
  {
    id: 'failed',
    label: '转写失败',
    tone: 'danger',
    help: '转写没有成功，可以重试，或删掉这段录音',
  },
  {
    id: 'similar',
    label: '可能是同一个人',
    tone: 'info',
    help: '合并录音库时同名，没法确定是不是一个人',
  },
  {
    id: 'disputed',
    label: '有人说不是自己',
    tone: 'warning',
    help: '原来标成的人说这不是 TA，试听后改成对的人',
  },
  {
    id: 'disowned',
    label: '分身被退回',
    tone: 'danger',
    help: '对方登录后说这个分身不是 TA，换一个邮箱或工号',
  },
  {
    id: 'fragments',
    label: '零碎片段',
    tone: 'info',
    help: '多是插话或附和，放一边不影响分身',
  },
  {
    id: 'mixed',
    label: '有空再看',
    tone: 'info',
    help: '大部分不像当初确认的人，不像的片段已自动排除，不影响分身；有空时听几段，补认给真正说话的人',
  },
];

export const minutes = (seconds: number) =>
  `${Math.max(0, Math.round(seconds / 60))} 分钟`;
export const span = (seconds: number) =>
  seconds < 60 ? `${Math.round(seconds)} 秒` : minutes(seconds);
// The speaker to hear is in the address, so a recording opened in a new tab opens on the voice heard here too.
export const recordingPath = (id: string, speaker?: string | null) =>
  `/library/${encodeURIComponent(id)}${speaker ? `?speaker=${encodeURIComponent(speaker)}` : ''}`;
