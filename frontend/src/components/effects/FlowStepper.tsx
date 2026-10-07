import { useId, useState, type ReactNode } from 'react';
import { LoaderCircle } from 'lucide-react';
import {
  PendingStep,
  PendingWorkProvider,
  useFlowPending,
} from '../../lib/pendingWork';
import { useMotionPreset } from '../../design/motion';
import Stepper from '../reactbits/Stepper';
import { Button } from '../ui/controls';

export interface FlowStep {
  id: string;
  title: string;
  content: ReactNode;
}

export function FlowStepper(props: FlowStepperProps) {
  return (
    <PendingWorkProvider>
      <FlowStepperBody {...props} />
    </PendingWorkProvider>
  );
}

interface FlowStepperProps {
  steps: FlowStep[];
  onComplete?: () => void;
  completedText?: string;
  finalActionText?: string;
  initialStep?: number;
  completeOnLast?: boolean;
  maxStep?: number;
  stageHeader?: ReactNode;
  footer?: ReactNode;
}

function FlowStepperBody({
  steps,
  onComplete,
  completedText = '已完成',
  finalActionText = '完成',
  initialStep = 1,
  completeOnLast = true,
  maxStep = steps.length,
  stageHeader,
  footer,
}: FlowStepperProps) {
  const { reduced } = useMotionPreset();
  const [current, setCurrent] = useState(initialStep);
  const [completed, setCompleted] = useState(false);
  const pending = useFlowPending(steps[current - 1]?.id);
  const descriptionId = useId();
  const nextDisabled =
    pending.locked ||
    (current >= maxStep && current < steps.length) ||
    (!completeOnLast && current === steps.length);
  const busyLabel = (
    <>
      <LoaderCircle
        aria-hidden
        className="size-4 animate-spin motion-reduce:animate-none"
      />
      {pending.label}
    </>
  );
  const finish = () => {
    if (pending.locked) return;
    setCompleted(true);
    onComplete?.();
  };
  const indicators = (
    step: number,
    active: number,
    select: (step: number) => void,
  ) => (
    <button
      type="button"
      aria-label={`第 ${step} 步：${steps[step - 1].title}`}
      aria-current={step === active ? 'step' : undefined}
      disabled={step > maxStep || (pending.locked && step !== active)}
      aria-disabled={step > maxStep || (pending.locked && step !== active)}
      aria-describedby={
        pending.locked && step !== active ? descriptionId : undefined
      }
      onClick={() => {
        if (!pending.locked && step <= maxStep) select(step);
      }}
      className={
        stageHeader
          ? 'stage-step size-11 shrink-0 rounded-full'
          : 'size-11 shrink-0 rounded-full border border-border bg-surface text-secondary aria-[current=step]:border-accent aria-[current=step]:bg-accent aria-[current=step]:text-on-accent'
      }
    >
      <span className={stageHeader ? 'sr-only' : undefined}>{step}</span>
    </button>
  );
  if (!steps.length) return null;
  return (
    <div
      className={`effects-stepper min-h-64 text-primary ${stageHeader ? 'stage-flow' : ''}`}
    >
      {stageHeader}
      <div className={stageHeader ? 'flow-panel' : undefined}>
        {completed ? (
          <p role="status">{completedText}</p>
        ) : reduced ? (
          <div className="flow-static rounded-xl border border-border bg-surface">
            <div
              aria-label="流程步骤"
              className="flow-indicators flex flex-wrap gap-3 p-5 sm:p-6"
            >
              {steps.map((step, index) => (
                <span key={step.id}>
                  {indicators(index + 1, current, setCurrent)}
                </span>
              ))}
            </div>
            <div className="effects-stepper-body min-h-24 p-5 sm:p-6">
              <PendingStep step={steps[current - 1].id}>
                {steps[current - 1].content}
              </PendingStep>
            </div>
            <div className="flex justify-end gap-2 p-5 sm:p-6">
              {current > 1 && (
                <Button
                  variant="secondary"
                  disabled={pending.locked}
                  aria-disabled={pending.locked}
                  aria-describedby={pending.locked ? descriptionId : undefined}
                  onClick={() => setCurrent(current - 1)}
                >
                  上一步
                </Button>
              )}
              <Button
                disabled={nextDisabled}
                loading={pending.locked}
                aria-disabled={nextDisabled}
                aria-describedby={pending.locked ? descriptionId : undefined}
                onClick={() =>
                  current === steps.length ? finish() : setCurrent(current + 1)
                }
              >
                {pending.locked
                  ? pending.label
                  : current === steps.length
                    ? completeOnLast
                      ? finalActionText
                      : '到最后了'
                    : '继续'}
              </Button>
            </div>
          </div>
        ) : (
          <Stepper
            initialStep={current}
            onStepChange={setCurrent}
            onFinalStepCompleted={finish}
            className="flow-animated !block !p-0"
            stepCircleContainerClassName="!max-w-none !rounded-xl !shadow-none"
            stepContainerClassName="flow-indicators !p-5 sm:!p-6 !overflow-x-auto"
            contentClassName="!px-0"
            footerClassName="!px-5 !pb-5 sm:!px-6 sm:!pb-6"
            backButtonText="上一步"
            nextButtonText={pending.locked ? busyLabel : '继续'}
            completeButtonText={
              pending.locked
                ? busyLabel
                : completeOnLast
                  ? finalActionText
                  : '到最后了'
            }
            backButtonProps={{
              type: 'button',
              disabled: pending.locked,
              'aria-disabled': pending.locked,
              'aria-describedby': pending.locked ? descriptionId : undefined,
              className:
                'min-h-11 rounded-full border border-border px-3 py-2 text-secondary',
            }}
            nextButtonProps={
              {
                type: 'button',
                disabled: nextDisabled,
                'aria-disabled': nextDisabled,
                'aria-busy': pending.locked,
                'aria-describedby': pending.locked ? descriptionId : undefined,
                className:
                  'inline-flex items-center gap-2 min-h-11 rounded-full bg-accent px-3 py-2 text-on-accent disabled:opacity-50',
              } as React.ButtonHTMLAttributes<HTMLButtonElement>
            }
            renderStepIndicator={({ step, currentStep, onStepClick }) =>
              indicators(step, currentStep, onStepClick)
            }
          >
            {steps.map((step) => (
              <div
                key={step.id}
                className="effects-stepper-body min-h-24 p-5 sm:p-6"
              >
                <PendingStep step={step.id}>{step.content}</PendingStep>
              </div>
            ))}
          </Stepper>
        )}
        {pending.locked && (
          <p
            id={descriptionId}
            role="status"
            className="px-5 text-sm text-secondary"
          >
            {pending.label} 请等待处理完成后再继续。
          </p>
        )}
        {pending.backgroundJob && (
          <Button variant="ghost" className="mx-5" onClick={pending.release}>
            在后台继续处理
          </Button>
        )}
        <PendingStep step={steps[current - 1].id}>{footer}</PendingStep>
      </div>
    </div>
  );
}
