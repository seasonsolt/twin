import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { AnimatePresence, motion } from 'motion/react';
import { FlowStepper } from '../components/effects/FlowStepper';
import {
  Badge,
  Button,
  Card,
  Field,
  Meter,
  Skeleton,
  Textarea,
  toast,
  useConfirm,
} from '../components/ui';
import { crossfade } from '../design/motion';
import { JobProgress } from '../features/jobs/JobProgress';
import { useJob } from '../features/jobs/useJob';
import { useQuestionnaire } from '../features/questionnaire/useQuestionnaire';
import { BuildSummary } from '../features/sources/SourceCards';
import type { BuildResult } from '../features/sources/types';
import { useStatus } from '../stores/status';

export function Questionnaire() {
  const active = useLocation().pathname === '/questionnaire';
  const draft = useQuestionnaire('initial', active);
  const confirm = useConfirm();
  const navigate = useNavigate();
  const [summary, setSummary] = useState<BuildResult | null>(null);
  const job = useJob<BuildResult>({
    kind: 'persona_build',
    storageKey: 'twin.next.job.personaBuild',
    active,
    onDone: (done, { restored }) => {
      setSummary(done.result ?? {});
      void useStatus.getState().refresh();
      if (!restored) toast('人格档案已根据问卷更新。', 'success');
    },
  });
  const needsWarning = draft.needsLeaveWarning;
  useEffect(() => {
    if (!active) return;
    const leave = (event: MouseEvent) => {
      const link =
        event.target instanceof Element ? event.target.closest('a') : null;
      const href = link?.getAttribute('href');
      if (
        !href?.startsWith('#/') ||
        href === window.location.hash ||
        !needsWarning() ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      )
        return;
      event.preventDefault();
      event.stopPropagation();
      void confirm({
        title: '草稿正在保存',
        body: '还有未保存的修改，保存请求正在进行。离开后仍会尝试保存，确定离开？',
        confirmLabel: '离开',
      }).then((ok) => {
        if (ok) void navigate(href.slice(1));
      });
    };
    document.addEventListener('click', leave, true);
    return () => document.removeEventListener('click', leave, true);
  }, [active, confirm, navigate, needsWarning]);

  const questions = draft.data?.questions ?? [];
  const answered = questions.filter((q) => draft.answers[q.id]?.trim()).length;
  const sections = [...new Set(questions.map((q) => q.section))];
  const firstUnanswered = questions.find((q) => !draft.answers[q.id]?.trim());
  const initialStep = firstUnanswered
    ? sections.indexOf(firstUnanswered.section) + 1
    : 1;
  const statusText = {
    idle: '回答会自动保存',
    pending: '等待保存…',
    saving: '正在保存…',
    saved: '已保存',
    error: '保存失败',
  }[draft.saveState];
  const submit = async () => {
    const replaces = draft.data?.status === 'submitted';
    if (
      !(await confirm({
        title: '提交回答？',
        body: `已答 ${answered} / ${questions.length} 题。答案会成为分身的记忆，保存后会尝试自动整理。任何题都可以跳过。${replaces ? '会替换上次提交的答案，并重新整理。' : ''}`,
        confirmLabel: '确认提交',
      }))
    )
      return;
    const result = await draft.submit();
    if (!result) return;
    toast(result.notice, 'success');
    void useStatus.getState().refresh();
    if (result.job_id) {
      setSummary(null);
      job.attach(result.job_id);
    }
  };
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">回答几个问题</h1>
        <p className="mt-2 text-sm text-secondary">
          想答哪题就答哪题，也可以直接添加记忆。回答自动保存，可以分几次填完。
        </p>
      </header>
      {draft.loading && <Skeleton className="h-40" />}
      {draft.error && (
        <div role="alert" className="text-danger">
          {draft.error}
          {!draft.data && (
            <Button variant="secondary" onClick={draft.reload}>
              重试加载
            </Button>
          )}
        </div>
      )}
      {draft.data && !draft.loading && (
        <>
          {draft.data.status === 'submitted' && (
            <p role="status" className="text-info">
              已于 {draft.data.submitted_at?.replace('T', ' ').slice(0, 16)}{' '}
              提交。可以修改后重新提交。
            </p>
          )}
          <Meter
            value={questions.length ? (answered / questions.length) * 100 : 0}
            label={`已答 ${answered} / ${questions.length} 题`}
          />
          <div role="status" className="min-h-6 text-sm text-secondary">
            <AnimatePresence mode="wait" initial={false}>
              <motion.span
                key={statusText}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={crossfade}
              >
                {statusText}
              </motion.span>
            </AnimatePresence>
          </div>
          {draft.saveError && (
            <p role="alert" className="text-danger">
              {draft.saveError}{' '}
              <Button
                variant="secondary"
                size="sm"
                onClick={() => void draft.flush()}
              >
                重试保存
              </Button>
            </p>
          )}
          <FlowStepper
            key={draft.data.round}
            initialStep={initialStep}
            completeOnLast={false}
            steps={sections.map((section) => ({
              id: section,
              title: section,
              content: (
                <section className="space-y-6 py-3" aria-label={section}>
                  <h2 className="text-lg font-semibold">{section}</h2>
                  {questions
                    .filter((q) => q.section === section)
                    .map((q) => {
                      const id = `answer-${q.id}`;
                      const skipped =
                        q.optional && !draft.answers[q.id]?.trim();
                      const help =
                        q.kind === '情境'
                          ? '写你当时真正会说出口的原话'
                          : '尽量举真实的例子';
                      return (
                        <div key={q.id} className="space-y-3">
                          <h3 id={`${id}-prompt`} className="font-medium">
                            {q.number}. {q.text}
                          </h3>
                          <div className="flex flex-wrap gap-2">
                            <Badge>{q.kind}</Badge>
                            {q.optional && (
                              <Badge>可跳过：不填即不授权采集这一项</Badge>
                            )}
                          </div>
                          <p
                            id={`${id}-facets`}
                            className="text-sm text-secondary"
                          >
                            相关内容：{q.facets.join('、')}
                          </p>
                          <Field id={id} label="回答" help={help}>
                            <Textarea
                              id={id}
                              maxLength={4000}
                              value={draft.answers[q.id] ?? ''}
                              disabled={draft.submitting}
                              aria-labelledby={`${id}-prompt`}
                              aria-describedby={`${id}-description ${id}-facets${q.optional ? ` ${id}-skip` : ''}`}
                              placeholder={help}
                              onChange={(event) =>
                                draft.change(q.id, event.target.value)
                              }
                            />
                          </Field>
                          {q.optional && (
                            <div className="space-y-2">
                              <Button
                                variant="secondary"
                                size="sm"
                                disabled={draft.submitting}
                                onClick={() => draft.change(q.id, '')}
                              >
                                跳过
                              </Button>
                              <p
                                id={`${id}-skip`}
                                className="text-sm text-secondary"
                              >
                                {skipped
                                  ? `留空即跳过，不采集：${q.facets.join('、')}`
                                  : '跳过会清空此题回答，提交后不采集相关内容。'}
                              </p>
                            </div>
                          )}
                        </div>
                      );
                    })}
                </section>
              ),
            }))}
          />
          <Card>
            <Button loading={draft.submitting} onClick={() => void submit()}>
              保存回答
            </Button>
            {draft.result && (
              <div role="status" className="mt-4 space-y-2 text-success">
                <p>{draft.result.notice}</p>
                <a href="#/sources" className="text-accent">
                  去资料与构建查看进度或构建
                </a>
              </div>
            )}
          </Card>
        </>
      )}
      <>
        <JobProgress
          state={job}
          onRetry={() => void job.start('/api/persona/build')}
        />
        {summary && (
          <Card>
            <p className="mb-3 text-success">
              构建完成。{' '}
              <a href="#/about" className="text-accent">
                看看我了解到的你
              </a>
              ，或者{' '}
              <a href="#/chat" className="text-accent">
                去和分身聊天
              </a>
              。
            </p>
            <BuildSummary result={summary} />
          </Card>
        )}
      </>
    </div>
  );
}
