import { useState, type ReactNode } from 'react';
import { useMotionPreset } from '../../design/motion';
import Stepper from '../reactbits/Stepper';
import { Button } from '../ui/controls';

export interface FlowStep {
  id: string;
  title: string;
  content: ReactNode;
}

export function FlowStepper({
  steps,
  onComplete,
  completedText = '已完成',
  initialStep = 1,
  completeOnLast = true,
}: {
  steps: FlowStep[];
  onComplete?: () => void;
  completedText?: string;
  initialStep?: number;
  completeOnLast?: boolean;
}) {
  const { reduced } = useMotionPreset();
  const [current, setCurrent] = useState(initialStep);
  const [completed, setCompleted] = useState(false);
  const finish = () => {
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
      onClick={() => select(step)}
      className="size-8 shrink-0 rounded-full border border-border bg-surface text-secondary aria-[current=step]:border-accent aria-[current=step]:bg-accent aria-[current=step]:text-on-accent"
    >
      {step}
    </button>
  );
  if (!steps.length) return null;
  return (
    <div className="effects-stepper min-h-64 text-primary">
      {completed ? (
        <p role="status">{completedText}</p>
      ) : reduced ? (
        <div className="rounded-xl border border-border bg-surface p-4">
          <div aria-label="流程步骤" className="mb-4 flex flex-wrap gap-3">
            {steps.map((step, index) => (
              <span key={step.id}>
                {indicators(index + 1, current, setCurrent)}
              </span>
            ))}
          </div>
          <div className="min-h-24">{steps[current - 1].content}</div>
          <div className="mt-4 flex justify-end gap-2">
            {current > 1 && (
              <Button
                variant="secondary"
                onClick={() => setCurrent(current - 1)}
              >
                上一步
              </Button>
            )}
            <Button
              disabled={!completeOnLast && current === steps.length}
              onClick={() =>
                current === steps.length ? finish() : setCurrent(current + 1)
              }
            >
              {current === steps.length
                ? completeOnLast
                  ? '完成'
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
          className="!block !p-0"
          stepCircleContainerClassName="!max-w-none !rounded-xl !shadow-none"
          stepContainerClassName="!p-4 !overflow-x-auto"
          contentClassName="!px-4"
          footerClassName="!px-4 !pb-4"
          backButtonText="上一步"
          nextButtonText="继续"
          backButtonProps={{
            type: 'button',
            className:
              'rounded-md border border-border px-3 py-2 text-secondary',
          }}
          nextButtonProps={
            {
              type: 'button',
              disabled: !completeOnLast && current === steps.length,
              'aria-label':
                current === steps.length
                  ? completeOnLast
                    ? '完成'
                    : '到最后了'
                  : '继续',
              className:
                'effects-stepper-next rounded-md bg-accent px-3 py-2 text-on-accent disabled:opacity-50',
              'data-label':
                current === steps.length
                  ? completeOnLast
                    ? '完成'
                    : '到最后了'
                  : '继续',
            } as React.ButtonHTMLAttributes<HTMLButtonElement>
          }
          renderStepIndicator={({ step, currentStep, onStepClick }) =>
            indicators(step, currentStep, onStepClick)
          }
        >
          {steps.map((step) => (
            <div key={step.id} className="min-h-24">
              {step.content}
            </div>
          ))}
        </Stepper>
      )}
    </div>
  );
}
