import { useEffect, useRef } from 'react';
import { Button, Card, Field, Input, useConfirm } from '../../components/ui';
import { api } from '../../lib/api';
import { getPersonaId } from '../../lib/persona';
import { usePersonaId, usePersonaState } from '../../lib/usePersonaState';

type WeComBotStatus = {
  bot_id: string;
  status: 'connected' | 'connecting' | 'error';
  detail: string;
  secret_set: boolean;
};

export function Channels() {
  const personaId = usePersonaId();
  const confirm = useConfirm();
  const revision = useRef(0);
  const [bot, setBot] = usePersonaState<WeComBotStatus | null>(null);
  const [form, setForm] = usePersonaState<{
    botId: string;
    secret: string;
  } | null>(null);
  const [saving, setSaving] = usePersonaState(false);
  const [error, setError] = usePersonaState('');
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      const current = revision.current;
      try {
        const data = await api<{ wecom: WeComBotStatus | null }>(
          '/api/channels',
          { signal: controller.signal },
        );
        if (current === revision.current) setBot(data.wecom);
      } catch {
        // Polling failures must not replace a form's server error.
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
  }, [personaId, setBot]);

  const save = async () => {
    if (!form || saving) return;
    setSaving(true);
    setError('');
    revision.current++;
    try {
      const result = await api<WeComBotStatus>('/api/channels/wecom', {
        method: 'PUT',
        json: {
          bot_id: form.botId.trim(),
          secret: form.secret.trim() || null,
        },
      });
      revision.current++;
      setBot(result);
      setForm(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '绑定失败，请重试');
    } finally {
      setSaving(false);
    }
  };

  const unbind = async () => {
    const accepted = await confirm({
      title: '解绑企业微信？',
      body: '解绑后，同事将不能通过这个机器人和分身聊天。',
      confirmLabel: '确认解绑',
      tone: 'danger',
    });
    if (!accepted || getPersonaId() !== personaId) return;
    setSaving(true);
    setError('');
    revision.current++;
    try {
      await api('/api/channels/wecom', { method: 'DELETE' });
      revision.current++;
      setBot(null);
      setForm(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '解绑失败，请重试');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="p-4 md:p-6">
      <h3 className="mb-3 text-md font-semibold md:text-lg">接入</h3>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">企业微信</span>
        <div className="flex min-w-0 flex-1 basis-full items-center gap-2 sm:basis-auto">
          {bot && (
            <span
              aria-hidden
              className={`size-2 shrink-0 rounded-full bg-current ${
                bot.status === 'connected'
                  ? 'text-success'
                  : bot.status === 'connecting'
                    ? 'text-warning'
                    : 'text-danger'
              }`}
            />
          )}
          <span className="text-secondary" role={bot ? 'status' : undefined}>
            {!bot
              ? '让同事在企业微信里单聊或 @ 这个分身'
              : bot.status === 'connected'
                ? '已连接，同事可以在企业微信里和他聊'
                : bot.status === 'connecting'
                  ? '连接中…'
                  : bot.detail}
          </span>
        </div>
        <Button
          size="sm"
          variant="secondary"
          disabled={saving}
          onClick={() => {
            setError('');
            setForm({ botId: bot?.bot_id ?? '', secret: '' });
          }}
        >
          {bot ? '修改' : '绑定'}
        </Button>
        {bot && (
          <Button
            size="sm"
            variant="ghost"
            disabled={saving}
            onClick={() => void unbind()}
          >
            解绑
          </Button>
        )}
      </div>
      {bot && (
        <p className="mt-2 break-all font-mono text-xs text-tertiary">
          {bot.bot_id}
        </p>
      )}
      {form && (
        <form
          className="mt-4 space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <Field id="wecom-bot-id" label="Bot ID">
            <Input
              id="wecom-bot-id"
              value={form.botId}
              onChange={(event) =>
                setForm({ ...form, botId: event.target.value })
              }
              required
              maxLength={128}
              autoComplete="off"
              disabled={saving}
            />
          </Field>
          <Field id="wecom-secret" label="Secret">
            <Input
              id="wecom-secret"
              type="password"
              autoComplete="off"
              placeholder={bot ? '不修改就留空' : ''}
              value={form.secret}
              onChange={(event) =>
                setForm({ ...form, secret: event.target.value })
              }
              maxLength={256}
              disabled={saving}
            />
          </Field>
          <p className="text-sm text-secondary">
            企业微信 → 工作台 → 智能机器人 → 创建 → API 模式 →
            使用长连接，然后复制 Bot ID 和 Secret。
          </p>
          <div className="flex gap-2">
            <Button type="submit" loading={saving}>
              保存
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={saving}
              onClick={() => {
                setForm(null);
                setError('');
              }}
            >
              取消
            </Button>
          </div>
        </form>
      )}
      {error && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {error}
        </p>
      )}
    </Card>
  );
}
