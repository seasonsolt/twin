import { Chestnut } from './Chestnut';
import { Wave } from './Wave';
import { Bun } from './Bun';
import { Stone } from './Stone';
import { Silver } from './Silver';
import type { AvatarSpec } from '../types';

export const presets = {
  chestnut: {
    name: '栗',
    Art: Chestnut,
    colors: ['#E6B897', '#3A2A24', '#2B323C', '#CBD2DB', '#34435A'],
  },
  wave: {
    name: '澜',
    Art: Wave,
    colors: ['#EBC0A0', '#34261F', '#3B4452', '#D3D9E0', '#2E3541'],
  },
  bun: {
    name: '禾',
    Art: Bun,
    colors: ['#E3AE8A', '#241D1B', '#5A6573', '#DCDFE4', '#4A5461'],
  },
  stone: {
    name: '石',
    Art: Stone,
    colors: ['#B9805B', '#1F1B19', '#26303D', '#CED5DE', '#5E2A33'],
  },
  silver: {
    name: '岚',
    Art: Silver,
    colors: ['#EEC6AC', '#BCC0C7', '#33435C', '#CDD4DE', '#27354A'],
  },
};
export type PresetId = keyof typeof presets;
export function presetId(id?: string | null): PresetId {
  return id && Object.hasOwn(presets, id) ? (id as PresetId) : 'chestnut';
}
export function presetSpec(id?: string | null): AvatarSpec {
  const key = presetId(id);
  return {
    schema_version: 1,
    avatar_id: key,
    palette: Object.fromEntries(
      ['skin', 'hair', 'outfit', 'background', 'accent'].map((color, i) => [
        color,
        presets[key].colors[i],
      ]),
    ),
    mouth_states: 4,
    stylized: true,
  };
}

export function PresetSvg({
  preset,
  blink = false,
  mouth = 0,
}: {
  preset?: string | null;
  blink?: boolean;
  mouth?: number;
}) {
  const id = presetId(preset);
  const { Art, name } = presets[id];
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 220 220"
      width="220"
      height="220"
      role="img"
      aria-label={`插画形象：${name}`}
      data-preset={id}
      data-mouth-level={mouth}
      className="block aspect-square size-full"
    >
      <Art blink={blink} mouth={mouth} />
    </svg>
  );
}
