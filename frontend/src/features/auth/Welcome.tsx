import { useCallback } from 'react';
import { Button, Steps, TeamMark, Toolbar } from '../../components/ui';
import { Claimed } from '../../pages/Claimed';
import { MemberVoice } from '../../pages/MemberVoice';
import type { Persona } from '../../stores/personas';
import { useTeamName } from '../../stores/team';
import { useWelcome } from '../../stores/welcome';

/**
 * The way in for someone who signs in with the company login (``#/welcome``): first find their own voice in the
 * meetings colleagues uploaded (``voice``), then look at the twin made from it, or made for them (``claim``). Either
 * step can be left for later; the app is reached from both.
 */
export function Welcome(
  props: { step: 'voice' } | { step: 'claim'; persona: Persona },
) {
  const voice = props.step === 'voice';
  const teamName = useTeamName();
  // Stable: the voice step loads again when the function it is given changes.
  const later = useCallback(() => {
    if (voice) useWelcome.getState().finishVoice();
    else useWelcome.getState().finishClaim();
  }, [voice]);
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="px-8 py-4">
        <Toolbar gap={4}>
          <TeamMark name={teamName} />
          <Steps
            label="步骤"
            steps={['认出你自己', '看看你的分身']}
            current={voice ? 0 : 1}
          />
          <Button variant="ghost" onClick={later}>
            稍后再说
          </Button>
        </Toolbar>
      </header>
      <main
        id="main"
        className="mx-auto w-full max-w-2xl flex-1 px-6 pt-6 pb-12"
      >
        {props.step === 'claim' ? (
          <Claimed persona={props.persona} />
        ) : (
          <MemberVoice onSkip={later} />
        )}
      </main>
    </div>
  );
}
