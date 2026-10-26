import { useCallback, useState } from 'react';
import { AvatarFrame, Button, Row, Stack, Text } from '../../components/ui';
import { usePersonaId } from '../../lib/usePersonaState';
import { AvatarPicker } from '../avatar/AvatarPicker';
import { AvatarPreview } from '../avatar/AvatarPreview';
import { presetId, presets } from '../avatar/presets';
import { SelfAssets } from '../assets/SelfAssets';
import type { useIdentity } from '../identity/useIdentity';
import { RecordingShortcut } from '../sources/MediaClaim';

/** The 形象和声音 tab: the illustration or portrait the twin shows, and the voice it speaks with. */
export function AssetsTab({
  identity,
  focusPortrait = false,
}: {
  identity: ReturnType<typeof useIdentity>;
  /** Opened by “换头像”: straight to the photo. */
  focusPortrait?: boolean;
}) {
  const personaId = usePersonaId();
  const modelUrl = identity.capabilities?.avatar_model?.url;
  const [model, setModel] = useState<{ url?: string; name: string | null }>({
    name: null,
  });
  const onModelNameChange = useCallback(
    (name: string | null) => setModel({ url: modelUrl, name }),
    [modelUrl],
  );
  const modelName = modelUrl && model.url === modelUrl ? model.name : null;
  const capabilities = identity.capabilities;
  return (
    <Stack gap={4}>
      <Row gap={4}>
        {capabilities &&
          (capabilities.avatar_image ||
            capabilities.avatar_model ||
            capabilities.avatar) && (
            <AvatarFrame size="2xl" decorative={false}>
              <AvatarPreview
                capabilities={capabilities}
                onModelNameChange={onModelNameChange}
              />
            </AvatarFrame>
          )}
        <Text size="sm" tone="secondary">
          形象：
          {modelName
            ? `${modelName}（3D 模型）`
            : identity.capabilities?.avatar_image
              ? '肖像照片'
              : `${presets[presetId(identity.data?.avatar)].name}（插画形象）`}
        </Text>
      </Row>
      {identity.avatarError && (
        <Row gap={2} wrap role="alert">
          <Text tone="danger">形象预览：{identity.avatarError}</Text>
          <Button variant="secondary" size="sm" onClick={identity.reload}>
            重试预览
          </Button>
        </Row>
      )}
      <AvatarPicker
        key={`avatar-${personaId}`}
        selected={identity.data?.avatar_preset ?? identity.data?.avatar}
        collapsed={
          !!(
            identity.capabilities?.avatar_image ||
            identity.capabilities?.avatar_model
          )
        }
        onSave={identity.savePreset}
      />
      <RecordingShortcut key={personaId} />
      <SelfAssets focusPortrait={focusPortrait} />
    </Stack>
  );
}
