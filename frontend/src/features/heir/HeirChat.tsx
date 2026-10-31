import { useEffect, useState, type FormEvent } from 'react';
import { ArrowUp } from 'lucide-react';
import {
  Button,
  ChatAction,
  ChatInput,
  ChatMessage,
  ChatSurface,
  Heading,
  Row,
  Select,
  Stack,
  Text,
  Toolbar,
  TypingIndicator,
} from '../../components/ui';
import { api } from '../../lib/api';
import { useAuth, type Heir } from '../../stores/auth';
import { MessageText } from '../chat/MessageText';
import { useConversation } from '../chat/useConversation';

/** One of the heir's own conversations, as ``GET /api/conversations`` lists it. */
interface Past {
  id: string;
  title: string;
}

/**
 * What an heir sees once they are in (P2.7): their own conversation with the twin and nothing else. Every screen says
 * whose memory this carries on and that it is not that person. The answers draw only on what the will gives them
 * (the server's ``heir:<id>`` tier); their earlier conversations are theirs alone. 离开 ends their session here.
 */
export function HeirChat({ heir }: { heir: Heir }) {
  const person = heir.person || 'TA';
  const chat = useConversation(true);
  const [past, setPast] = useState<Past[]>([]);
  const [leaving, setLeaving] = useState(false);
  const [error, setError] = useState('');
  const { written } = chat;
  useEffect(() => {
    const controller = new AbortController();
    api<Past[]>('/api/conversations', { signal: controller.signal })
      .then((items) => setPast(Array.isArray(items) ? items : []))
      .catch(() => {});
    return () => controller.abort();
  }, [written]);
  const send = (event?: FormEvent) => {
    event?.preventDefault();
    void chat.send();
  };
  const leave = async () => {
    setLeaving(true);
    setError('');
    try {
      await useAuth.getState().leave();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '没能离开，请重试');
      setLeaving(false);
    }
  };
  const failure = error || chat.error;
  return (
    <main className="mx-auto flex h-dvh w-full max-w-3xl flex-col gap-4 px-4 py-6">
      <Toolbar as="header">
        <Stack gap={1}>
          <Heading level={1} size="page">
            {person}的记忆延续
          </Heading>
          <Text size="sm" tone="secondary">
            不是{person}本人
          </Text>
        </Stack>
        <Row gap={2}>
          {past.length > 0 && (
            <Select
              aria-label="以前的对话"
              value={chat.conversationId ?? ''}
              onChange={(event) => {
                if (event.target.value) void chat.resume(event.target.value);
              }}
            >
              <option value="">以前的对话</option>
              {past.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title || '对话'}
                </option>
              ))}
            </Select>
          )}
          <Button
            variant="ghost"
            size="sm"
            disabled={!chat.turns.length}
            onClick={chat.clear}
          >
            新对话
          </Button>
          <Button
            variant="ghost"
            size="sm"
            loading={leaving}
            onClick={() => void leave()}
          >
            离开
          </Button>
        </Row>
      </Toolbar>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {chat.turns.length === 0 && !chat.loading ? (
          <Text tone="secondary" align="center">
            {heir.name}，想问{person}什么，就在下面写。
          </Text>
        ) : (
          <Stack gap={4}>
            {chat.turns.map((turn) => (
              <ChatMessage
                key={turn.id}
                speaker={turn.role}
                aria-label={turn.role === 'user' ? '你说' : '回复'}
              >
                <MessageText
                  text={turn.content}
                  plain={turn.role === 'user'}
                  streaming={chat.busy && turn.id === chat.newest}
                />
              </ChatMessage>
            ))}
            {chat.busy && !chat.newest && <TypingIndicator />}
          </Stack>
        )}
      </div>
      {failure && (
        <Text role="alert" size="sm" tone="danger">
          {failure}
        </Text>
      )}
      <form onSubmit={send}>
        <ChatSurface variant="composer">
          <ChatInput
            aria-label="你说"
            maxRows={5}
            maxLength={4000}
            value={chat.draft}
            onChange={(event) => chat.setDraft(event.target.value)}
            onSend={send}
            placeholder={`和${person}的记忆聊点什么…`}
          />
          <Row gap={1} justify="end">
            <ChatAction
              type="submit"
              variant="send"
              aria-label="发送"
              loading={chat.busy}
              disabled={!chat.draft.trim() || chat.loading}
            >
              {!chat.busy && <ArrowUp className="size-5" aria-hidden />}
            </ChatAction>
          </Row>
        </ChatSurface>
      </form>
    </main>
  );
}
