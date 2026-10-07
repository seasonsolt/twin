import { useState } from 'react';
import { useNavigate } from 'react-router';
import { FlowStepper } from '../components/effects/FlowStepper';
import { Button } from '../components/ui';
import { StageHeader } from '../components/layout/StageHeader';
import { PersonaSwitcher } from '../components/layout/PersonaSwitcher';
import { IdentityForm } from '../features/identity/IdentityForm';
import { SelfAssets } from '../features/assets/SelfAssets';
import { RecordingShortcut } from '../features/sources/MediaClaim';
import type { IdentityData } from '../features/identity/useIdentity';
import { api } from '../lib/api';
import { useStatus } from '../stores/status';
import { Memories } from './Memories';

export function Onboarding({
  identity,
  onDone,
}: {
  identity: IdentityData;
  onDone: () => void;
}) {
  const [saved, setSaved] = useState(false);
  const [twin, setTwin] = useState({
    name: identity.name,
    about: identity.about,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const navigate = useNavigate();
  const finish = async () => {
    if (identity.onboarding_pending) {
      try {
        await api('/api/identity/onboarding-complete', { method: 'POST' });
      } catch (failure) {
        setError(
          failure instanceof Error ? failure.message : '保存失败，请重试',
        );
        return;
      }
    }
    onDone();
    navigate('/chat');
  };
  const skip = async () => {
    if (saved) {
      await finish();
      return;
    }
    setBusy(true);
    setError('');
    try {
      await api('/api/identity', {
        method: 'PUT',
        json: { name: identity.name.slice(0, 20), about: identity.about || '' },
      });
      await useStatus.getState().refresh();
      await finish();
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : '暂时无法跳过，请重试',
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <main className="onboarding-page min-h-dvh">
      <FlowStepper
        stageHeader={
          <StageHeader
            variant="expanded"
            className="onboarding-stage"
            name={twin.name.trim() || '新分身'}
            left={<PersonaSwitcher stage />}
            intro={
              <p className="stage-caption">{twin.about || '让我们认识一下'}</p>
            }
          />
        }
        footer={
          <>
            {error && (
              <p role="alert" className="px-5 text-danger">
                {error}
              </p>
            )}
            <Button
              className="mx-5 my-6"
              variant="ghost"
              loading={busy}
              onClick={() => void skip()}
            >
              跳过
            </Button>
          </>
        }
        maxStep={saved ? 4 : 1}
        onComplete={() => void finish()}
        finalActionText="开始聊天"
        steps={[
          {
            id: 'identity',
            title: '你是谁',
            content: (
              <div className="space-y-4">
                <h2 className="text-xl font-semibold">你是谁</h2>
                <IdentityForm
                  identity={{
                    name: identity.onboarding_pending ? identity.name : '',
                    about: identity.about,
                  }}
                  onDraftChange={setTwin}
                  onSaved={(next) => {
                    setTwin(next);
                    setSaved(true);
                  }}
                />
                {saved && <p role="status">已保存，可以继续添加记忆。</p>}
              </div>
            ),
          },
          {
            id: 'assets',
            title: '形象和声音',
            content: (
              <div className="space-y-4">
                <h2 className="text-xl font-semibold">形象和声音</h2>
                <p className="text-secondary">
                  可以现在设置，也可以直接继续，以后在关于他里更换。
                </p>
                <RecordingShortcut />
                <SelfAssets />
              </div>
            ),
          },
          { id: 'memories', title: '添加记忆', content: <Memories embedded /> },
          {
            id: 'chat',
            title: '开始聊天',
            content: (
              <div className="space-y-4">
                <h2 className="text-xl font-semibold">开始聊天</h2>
                <p>记忆会慢慢整理好，现在可以聊聊了。</p>
              </div>
            ),
          },
        ]}
      />
    </main>
  );
}
