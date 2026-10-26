import { Skeleton, Stack, Text } from '../../components/ui';
import { useStatus } from '../../stores/status';

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
export function ExternalServices() {
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
