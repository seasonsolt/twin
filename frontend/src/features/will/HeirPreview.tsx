import { useEffect, useRef, useState, type FormEvent } from 'react';
import {
  Badge,
  Button,
  ChatMessage,
  Notice,
  Row,
  Stack,
} from '../../components/ui';
import { api } from '../../lib/api';
import { readSSE } from '../../lib/sse';
import { usePersonas } from '../../stores/personas';
import { useStatus } from '../../stores/status';
import { MessageText } from '../chat/MessageText';
import { HeirComposer, HeirGreeting, HeirHeading } from '../heir/HeirChat';
import type { ChatReply, Withheld } from '../chat/types';
import type { Heir } from './types';

// The conversation sent back each time, as the chat keeps it (``MAX_CHAT_TURNS``).
const MAX_TURNS = 40;

interface Turn {
  id: string;
  role: 'user' | 'twin';
  content: string;
  /** What the person's own retrieval found for this question that the will does not give this heir. */
  withheld?: Withheld[];
}

/**
 * 预演 (P2.6): the person asks as one heir would, and is answered from what the will gives that heir alone, as the
 * heir would be. Under each answer, what it would also have drawn on for the person and the heir is not given, by
 * aspect, for changing the will. Nothing of it is kept: the rehearsal lives in this panel and is gone when it closes.
 */
export function HeirPreview({
  heir,
  onEdit,
  onBack,
  onRefused,
}: {
  heir: Heir;
  onEdit: () => void;
  onBack: () => void;
  /** The server would not rehearse (the memory is sealed, or the heir is gone); true when it was handled. */
  onRefused: (failure: unknown) => boolean;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const request = useRef<AbortController | null>(null);
  // Who the heir would be told this memory carries on, as on their own page.
  const status = useStatus((state) => state.data);
  const persona = usePersonas((state) =>
    state.items.find((item) => item.id === state.id),
  );
  const person = status?.target_name || persona?.name || 'TA';

  useEffect(() => () => request.current?.abort(), []);

  const ask = async (event?: FormEvent) => {
    event?.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    const controller = new AbortController();
    request.current = controller;
    const asked: Turn = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
    };
    const pending = [...turns, asked];
    setTurns(pending);
    setDraft('');
    setBusy(true);
    setError('');
    try {
      const response = await api<Response>('/api/persona/chat/stream', {
        method: 'POST',
        json: {
          messages: pending
            .slice(-MAX_TURNS)
            .map(({ role, content }) => ({ role, content })),
          preview: true,
          heir: heir.heir_id,
        },
        signal: controller.signal,
        responseType: 'stream',
      });
      const twin: Turn = { id: crypto.randomUUID(), role: 'twin', content: '' };
      let finished = false;
      for await (const { event, data } of readSSE(
        response,
        controller.signal,
      )) {
        if (event === 'delta') {
          twin.content += (data as { text: string }).text;
          setTurns([...pending, { ...twin }]);
        } else if (event === 'final') {
          const reply = data as ChatReply;
          twin.content = reply.reply;
          twin.withheld = reply.preview?.withheld ?? [];
          setTurns([...pending, { ...twin }]);
          finished = true;
        } else if (event === 'error') {
          throw new Error(
            (data as { detail: string }).detail || '分身没能回复，请重试',
          );
        }
      }
      if (!finished) throw new Error('回复中断，请重试');
    } catch (failure) {
      if (controller.signal.aborted || onRefused(failure)) return;
      setTurns(turns);
      setDraft(text);
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  };

  return (
    <Stack gap={4}>
      <HeirHeading person={person} nested />
      {turns.length ? (
        <Stack gap={4} role="log" aria-label="预演">
          {turns.map((turn, index) => (
            <ChatMessage
              key={turn.id}
              speaker={turn.role}
              aria-label={turn.role === 'user' ? `${heir.name}问` : '分身回复'}
            >
              <Stack gap={2}>
                <MessageText
                  text={turn.content}
                  plain={turn.role === 'user'}
                  streaming={busy && index === turns.length - 1}
                />
                {!!turn.withheld?.length && (
                  <Row gap={2} wrap aria-label={`没给${heir.name}的`}>
                    {turn.withheld.map((item) => (
                      <Badge key={item.id} title={item.text}>
                        未用 · {item.facet}
                      </Badge>
                    ))}
                  </Row>
                )}
              </Stack>
            </ChatMessage>
          ))}
        </Stack>
      ) : (
        <HeirGreeting heir={heir.name} person={person} />
      )}
      {error && (
        <Notice tone="danger" role="alert">
          {error}
        </Notice>
      )}
      <HeirComposer
        person={person}
        label={`以${heir.name}的身份问`}
        value={draft}
        onChange={setDraft}
        onSend={(event) => void ask(event)}
        busy={busy}
      />
      <Row justify="between">
        <Button variant="ghost" onClick={onBack}>
          返回
        </Button>
        <Button variant="secondary" onClick={onEdit}>
          改遗嘱
        </Button>
      </Row>
    </Stack>
  );
}
