import { useState } from 'react';
import { toast } from '../../components/ui';
import { PresetSvg, presetId, presets } from './presets';

export function AvatarPicker({
  selected,
  collapsed,
  onSave,
}: {
  selected?: string | null;
  collapsed: boolean;
  onSave(preset: string): Promise<void>;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const picker = (
    <div className="space-y-3">
      <h3 className="font-semibold">选择插画形象</h3>
      <div
        className="flex gap-4 overflow-x-auto p-2"
        role="group"
        aria-label="选择插画形象"
        aria-busy={busy !== null}
      >
        {Object.entries(presets).map(([id, entry]) => (
          <button
            key={id}
            type="button"
            className="w-20 shrink-0 space-y-2 rounded-lg text-center disabled:opacity-60"
            aria-label={`选择${entry.name}`}
            aria-pressed={presetId(selected) === id}
            disabled={busy !== null}
            onClick={() => {
              if (presetId(selected) === id) return;
              setBusy(id);
              void onSave(id)
                .then(() => toast('插画形象已保存'))
                .catch((error: unknown) =>
                  toast(
                    error instanceof Error ? error.message : '保存失败，请重试',
                    'danger',
                  ),
                )
                .finally(() => setBusy(null));
            }}
          >
            <span
              className="block aspect-square overflow-hidden rounded-full"
              style={{
                outline:
                  presetId(selected) === id
                    ? `3px solid ${entry.colors[4]}`
                    : undefined,
                outlineOffset: 3,
              }}
            >
              <PresetSvg preset={id} />
            </span>
            <span className="block">
              {busy === id ? '保存中…' : entry.name}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
  return collapsed ? (
    <details className="rounded-xl bg-surface p-4">
      <summary className="cursor-pointer">没有照片时使用的插画形象</summary>
      <div className="mt-4">{picker}</div>
    </details>
  ) : (
    picker
  );
}
