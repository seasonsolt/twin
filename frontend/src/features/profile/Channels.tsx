import { useEffect } from 'react';
import { Card } from '../../components/ui';
import { api } from '../../lib/api';
import { usePersonaId, usePersonaState } from '../../lib/usePersonaState';

type WeComBotStatus = {
  bot_id: string;
  status: 'connected' | 'connecting' | 'error';
  detail: string;
};

export function Channels() {
  const personaId = usePersonaId();
  const [bots, setBots] = usePersonaState<WeComBotStatus[]>([]);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      try {
        const data = await api<{ wecom: WeComBotStatus[] }>('/api/channels', {
          signal: controller.signal,
        });
        setBots(data.wecom ?? []);
      } catch {
        // Connection state is optional; a failed request must not block the profile.
      } finally {
        if (!controller.signal.aborted)
          timer = setTimeout(() => void refresh(), 5000);
      }
    };
    void refresh();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [personaId, setBots]);
  if (!bots.length) return null;
  return (
    <Card className="p-4 md:p-6">
      <h3 className="mb-3 text-md font-semibold md:text-lg">接入</h3>
      {bots.map((bot) => (
        <div
          key={bot.bot_id}
          className="flex flex-wrap items-center gap-2 text-sm"
        >
          <span>企业微信</span>
          <span
            aria-hidden
            className={`size-2 rounded-full bg-current ${
              bot.status === 'connected'
                ? 'text-success'
                : bot.status === 'connecting'
                  ? 'text-warning'
                  : 'text-danger'
            }`}
          />
          <span className="text-secondary" role="status">
            {bot.status === 'connected'
              ? '已连接，同事可以在企业微信里和他聊'
              : bot.status === 'connecting'
                ? '连接中…'
                : bot.detail}
          </span>
        </div>
      ))}
    </Card>
  );
}
