import { useEffect, useRef, useState } from 'react';
import {
  Button,
  Card,
  Dialog,
  Field,
  LevelDots,
  Row,
  Segmented,
  Skeleton,
  Stack,
  Text,
  Textarea,
  toast,
} from '../../components/ui';
import { api } from '../../lib/api';

/** One question of 补一补, asked for a facet the twin does not know well yet. */
interface Question {
  id: string;
  text: string;
  facet: string;
  facet_name: string;
  level: number;
  level_label: string;
}
type Choice = 'colleague' | 'self' | 'none';
/** What the answer was read into: a conclusion for a facet, and who may use it until the person says. */
interface Draft {
  facet: string;
  facet_name: string;
  statement: string;
  tier: 'colleague' | 'self';
}
interface Worth {
  facet_id: string;
  facet: string;
  before: number;
  after: number;
  before_label: string;
  after_label: string;
}
const CHOICES: { id: Choice; label: string }[] = [
  { id: 'colleague', label: '同事能用' },
  { id: 'self', label: '只有我' },
  { id: 'none', label: '不存' },
];

/** Where the questions are taken from: what the twin knows least, or the one facet or aspect the person opened. */
export interface FillScope {
  facet?: string;
  dimension?: string;
  /** The aspect to ask about when what the twin knows least has nothing to ask: its facets the person keeps to
   * themself are not asked unprompted, but the aspect was shown as wanting more. */
  otherwise?: string;
}

/**
 * 补一补: a few questions about what the twin does not know of its person yet. An answer is first read into the
 * memories it would become; the person looks at them, says for each who may use it (or not to keep it), and only then
 * is anything stored. The level of the facet before and after is shown, so they know what the answer is worth.
 */
export function FillDialog({
  open,
  onOpenChange,
  scope,
  onKept,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  scope?: FillScope;
  /** Something was stored: the page showing what the twin knows reads it again. */
  onKept: () => void;
}) {
  const [questions, setQuestions] = useState<Question[] | null>(null);
  const [index, setIndex] = useState(0);
  const [answer, setAnswer] = useState('');
  const [drafts, setDrafts] = useState<Draft[] | null>(null);
  const [choices, setChoices] = useState<Choice[]>([]);
  const [worth, setWorth] = useState<Worth[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const kept = useRef(0);
  const question = questions?.[index];

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    const query = new URLSearchParams();
    if (scope?.facet) query.set('facet', scope.facet);
    if (scope?.dimension) query.set('dimension', scope.dimension);
    const fetchQuestions = (path: URLSearchParams) =>
      api<{ questions: Question[] }>(
        `/api/persona/fill${path.size ? `?${path}` : ''}`,
        { signal: controller.signal },
      );
    setQuestions(null);
    setIndex(0);
    setAnswer('');
    setDrafts(null);
    setError('');
    kept.current = 0;
    void fetchQuestions(query)
      .then((reply) =>
        reply.questions.length || query.size || !scope?.otherwise
          ? reply
          : fetchQuestions(new URLSearchParams({ dimension: scope.otherwise })),
      )
      .then((reply) => setQuestions(reply.questions))
      .catch((failure: unknown) => {
        if (controller.signal.aborted) return;
        setQuestions([]);
        setError(failure instanceof Error ? failure.message : '加载失败');
      });
    return () => controller.abort();
  }, [open, scope?.facet, scope?.dimension, scope?.otherwise]);

  const items = (list: Draft[], picked: Choice[]) =>
    list.map((draft, i) => ({
      facet: draft.facet,
      statement: draft.statement,
      choice: picked[i],
    }));
  const body = (list: Draft[], picked: Choice[]) => ({
    question: question?.id,
    facet: question?.facet,
    items: items(list, picked),
  });

  const read = async () => {
    if (!question || !answer.trim()) return;
    setBusy(true);
    setError('');
    try {
      const reply = await api<{ drafts: Draft[]; changes: Worth[] }>(
        '/api/persona/fill/draft',
        {
          method: 'POST',
          json: { question: question.id, facet: question.facet, answer },
        },
      );
      setDrafts(reply.drafts);
      setChoices(reply.drafts.map((draft) => draft.tier));
      setWorth(reply.changes);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '整理失败');
    } finally {
      setBusy(false);
    }
  };

  const choose = async (at: number, choice: Choice) => {
    if (!drafts) return;
    const picked = choices.map((current, i) => (i === at ? choice : current));
    setChoices(picked);
    try {
      const reply = await api<{ changes: Worth[] }>(
        '/api/persona/fill/preview',
        { method: 'POST', json: body(drafts, picked) },
      );
      setWorth(reply.changes);
    } catch {
      // The level shown may be a step behind; keeping is still checked by the server.
    }
  };

  // However the sitting ends (the last question, 关闭, Esc), what was stored is told once and the page reads it again.
  const finish = () => {
    onOpenChange(false);
    if (kept.current > 0) {
      toast(`存了 ${kept.current} 条，分身正在整理`, 'success');
      onKept();
    }
    kept.current = 0;
  };

  const next = () => {
    setAnswer('');
    setDrafts(null);
    setError('');
    if (questions && index + 1 < questions.length) setIndex(index + 1);
    else finish();
  };

  const keep = async () => {
    if (!drafts || !choices.some((choice) => choice !== 'none')) return;
    setBusy(true);
    setError('');
    try {
      const reply = await api<{ saved: number }>('/api/persona/fill/keep', {
        method: 'POST',
        json: body(drafts, choices),
      });
      kept.current += reply.saved;
      next();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '没存上，请重试');
    } finally {
      setBusy(false);
    }
  };

  const total = questions?.length ?? 0;
  const raised = worth.filter((change) => change.after > change.before);
  return (
    <Dialog
      open={open}
      onOpenChange={(opened) => (opened ? onOpenChange(true) : finish())}
      title="补一补"
    >
      {questions === null ? (
        <Skeleton className="h-40" />
      ) : !question ? (
        <Stack gap={3}>
          <Text tone="secondary">
            {error || '暂时没有要补的，分身对你已经了解得不错。'}
          </Text>
          <Row justify="end">
            <Button variant="ghost" onClick={finish}>
              关闭
            </Button>
          </Row>
        </Stack>
      ) : (
        <Stack gap={4}>
          {total > 1 && (
            <Text size="sm" tone="tertiary">
              第 {index + 1} 题，共 {total} 题
            </Text>
          )}
          <Stack gap={1}>
            <Text size="sm" tone="secondary">
              {question.facet_name}
            </Text>
            <Text weight="medium">{question.text}</Text>
          </Stack>
          <Field id="fill-answer" label="你的回答">
            <Textarea
              id="fill-answer"
              rows={3}
              maxRows={8}
              maxLength={2000}
              value={answer}
              disabled={busy}
              onChange={(event) => {
                setAnswer(event.target.value);
                setDrafts(null);
              }}
            />
          </Field>
          {drafts === null ? (
            <Row justify="end">
              <Button
                loading={busy}
                disabled={!answer.trim()}
                onClick={() => void read()}
              >
                整理
              </Button>
            </Row>
          ) : (
            <Stack gap={3}>
              <Text size="sm" tone="secondary">
                {drafts.length
                  ? `整理成 ${drafts.length} 条`
                  : '没整理出能存的内容，换个说法再试'}
              </Text>
              {drafts.map((draft, i) => (
                <Card key={draft.statement} variant="soft" padding="md">
                  <Stack gap={2}>
                    <Text>{draft.statement}</Text>
                    <Segmented
                      label="谁能用这条"
                      value={choices[i] ?? draft.tier}
                      options={CHOICES}
                      onChange={(choice) => void choose(i, choice)}
                    />
                  </Stack>
                </Card>
              ))}
              {raised.map((change) => (
                <Row
                  key={change.facet_id}
                  gap={2}
                  role="img"
                  aria-label={`存了以后：${change.facet}从${change.before_label}升到${change.after_label}`}
                >
                  <Text as="span" size="sm">
                    {change.facet}
                  </Text>
                  <LevelDots level={change.before} />
                  <Text as="span" size="sm" tone="tertiary" aria-hidden>
                    →
                  </Text>
                  <LevelDots level={change.after} />
                  <Text as="span" size="sm" tone="secondary">
                    {change.after_label}
                  </Text>
                </Row>
              ))}
            </Stack>
          )}
          {error && (
            <Text role="alert" size="sm" tone="danger">
              {error}
            </Text>
          )}
          <Row gap={2} justify="end">
            <Button variant="ghost" disabled={busy} onClick={next}>
              跳过
            </Button>
            <Button
              loading={busy && drafts !== null}
              disabled={!drafts || !choices.some((choice) => choice !== 'none')}
              onClick={() => void keep()}
            >
              存进记忆
            </Button>
          </Row>
        </Stack>
      )}
    </Dialog>
  );
}
