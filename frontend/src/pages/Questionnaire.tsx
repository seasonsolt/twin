import { useEffect, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router';
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
  const [query] = useSearchParams();
  const round = query.get('round') === 'retest' ? 'retest' : 'initial';
  const draft = useQuestionnaire(round, active);
  const confirm = useConfirm();
  const navigate = useNavigate();
  const [summary, setSummary] = useState<BuildResult | null>(null);
  const job = useJob<BuildResult>({
    kind: 'persona_build',
    storageKey: 'twin.next.job.personaBuild',
    active: active && round === 'initial',
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
    const replaces = round === 'initial' && draft.data?.status === 'submitted';
    if (
      !(await confirm({
        title: round === 'retest' ? '提交重测？' : '提交建档问卷？',
        body: `已答 ${answered} / ${questions.length} 题。${round === 'retest' ? '重测仅记录答案，不导入人格档案。' : '答案会导入为问卷资料；需要重新构建人格档案，后端会尝试自动开始。测试题不进档案，可跳过题留空即不授权采集对应细项。'}${replaces ? '会替换上次提交的答案，并重新构建档案。' : ''}`,
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
        <h1 className="text-2xl font-semibold">
          {round === 'retest' ? '问卷重测' : '建档问卷'}
        </h1>
        <p className="mt-2 text-sm text-secondary">
          {round === 'retest'
            ? `再答一次 ${questions.length} 道测试题，不要翻看上次的答案。重测仅记录答案，不进入建档证据。${draft.data?.retest_from ? `建议 ${draft.data.retest_from} 之后再做。` : ''}`
            : '按维度分组，回答自动保存成草稿，可以分几次填完。情境题请写你会说出口的原话。测试题不进档案；可跳过题不填即不授权。'}
        </p>
        <nav aria-label="问卷轮次" className="mt-3 flex gap-4 text-accent">
          <a
            href="#/questionnaire"
            aria-current={round === 'initial' ? 'page' : undefined}
          >
            第一轮
          </a>
          <a
            href="#/questionnaire?round=retest"
            aria-current={round === 'retest' ? 'page' : undefined}
          >
            重测
          </a>
        </nav>
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
              {round === 'initial' && (
                <>
                  {' '}
                  <a
                    href="#/questionnaire?round=retest"
                    className="text-accent"
                  >
                    三周后去做重测
                  </a>
                </>
              )}
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
            key={`${round}-${draft.data.round}`}
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
                            {q.test && (
                              <Badge tone="warning">
                                测试题：不进档案，只用来检验分身
                              </Badge>
                            )}
                            {q.optional && (
                              <Badge>可跳过：不填即不授权采集这一项</Badge>
                            )}
                          </div>
                          <p
                            id={`${id}-facets`}
                            className="text-sm text-secondary"
                          >
                            对应细项：{q.facets.join('、')}
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
                                  : '跳过会清空此题回答，提交后不采集对应细项。'}
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
              {round === 'retest' ? '提交重测' : '交卷并构建档案'}
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
      {round === 'initial' && (
        <>
          <JobProgress
            state={job}
            onRetry={() => void job.start('/api/persona/build')}
          />
          {summary && (
            <Card>
              <p className="mb-3 text-success">
                构建完成。{' '}
                <a href="#/persona" className="text-accent">
                  查看人格档案与完成度
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
      )}
    </div>
  );
}
