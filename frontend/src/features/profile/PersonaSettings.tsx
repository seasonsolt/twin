import { useState } from 'react';
import { useNavigate } from 'react-router';
import {
  Button,
  SettingsDialog,
  Skeleton,
  Stack,
  Text,
  useConfirm,
} from '../../components/ui';
import { api } from '../../lib/api';
import { forgetPersona } from '../../lib/persona';
import { usePersonas } from '../../stores/personas';
import { useStatus } from '../../stores/status';
import { AliasList } from '../identity/AliasList';
import { Channels } from './Channels';

export const settingsSections = [
  { key: 'channels', label: '接入' },
  { key: 'aliases', label: '别名' },
  { key: 'services', label: '外部服务' },
  { key: 'delete', label: '删除分身' },
];
const backendNames: Record<string, string> = {
  llm: '大模型',
  llm_fallback: '备选大模型',
  embed: '向量',
  tts: '朗读',
  asr: '语音识别',
  video: '视频生成',
  vision: '形象提取',
  judge: '回答检查',
  search: '网页搜索',
};

/** Where the twin's data leaves this machine, so the person can tell at a glance. */
function ExternalServices() {
  const status = useStatus((state) => state.data);
  if (!status) return <Skeleton className="h-16" />;
  const external = status.egress.filter((row) => row.external);
  return external.length ? (
    <Stack as="ul" gap={2}>
      {external.map((row, i) => (
        <Text as="li" key={`${row.kind}-${i}`} size="sm">
          {backendNames[row.kind] ??
            (row.kind.startsWith('judge') ? '回答检查' : '数据处理')}
          ：{row.host || '地址未提供'}
        </Text>
      ))}
    </Stack>
  ) : (
    <Text size="sm" tone="secondary">
      目前没有使用外部服务。
    </Text>
  );
}

/** The twin's settings over its page: channels, the names it goes by, where data leaves, and deleting it. */
export function PersonaSettings({
  section,
  onSection,
  name,
}: {
  /** The section open, or null while the dialog is closed. */
  section: string | null;
  onSection: (section: string | null) => void;
  name?: string;
}) {
  const current = usePersonas((state) =>
    state.items.find((item) => item.id === state.id),
  );
  const navigate = useNavigate();
  const confirm = useConfirm();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const remove = async () => {
    if (!current || (current.is_default && !current.retirable) || busy) return;
    const deleting = current;
    if (
      !(await confirm({
        title: `删除「${deleting.name}」？`,
        body: deleting.is_default
          ? '它是空的，删除后不能恢复'
          : '删除后 7 天内可以在团队页的「已删除」里恢复',
        confirmLabel: '删除分身',
        tone: 'danger',
      })) ||
      usePersonas.getState().id !== deleting.id
    )
      return;
    setBusy(true);
    setError('');
    try {
      await api(`/api/personas/${deleting.id}`, { method: 'DELETE' });
      forgetPersona(deleting.id);
      await usePersonas.getState().refresh();
      navigate('/team');
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '操作失败，请重试');
    } finally {
      setBusy(false);
    }
  };
  return (
    <SettingsDialog
      open={section !== null}
      onOpenChange={(open) => onSection(open ? 'channels' : null)}
      title="分身设置"
      note={name || current?.name}
      sections={settingsSections}
      active={section ?? 'channels'}
      onSelect={onSection}
    >
      {section === 'channels' && <Channels />}
      {section === 'aliases' && <AliasList />}
      {section === 'services' && <ExternalServices />}
      {section === 'delete' && (
        <Stack gap={3} align="start">
          {current?.is_default && !current.retirable ? (
            <Text tone="secondary">默认分身不能删除</Text>
          ) : (
            current && (
              <Button
                variant="danger"
                loading={busy}
                onClick={() => void remove()}
              >
                删除这个分身
              </Button>
            )
          )}
          {error && (
            <Text role="alert" tone="danger">
              {error}
            </Text>
          )}
        </Stack>
      )}
    </SettingsDialog>
  );
}
