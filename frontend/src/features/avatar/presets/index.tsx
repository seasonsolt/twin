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
    colors: ['#F3C4A2', '#4A2E26', '#E2A33B', '#F6C9A8', '#C9862A'],
  },
  wave: {
    name: '澜',
    Art: Wave,
    colors: ['#F6C8A4', '#B8523A', '#2F8C83', '#FFD9C2', '#F2C14E'],
  },
  bun: {
    name: '禾',
    Art: Bun,
    colors: ['#EDB48C', '#2C2320', '#7C8A4A', '#F7DF8E', '#E46A4E'],
  },
  stone: {
    name: '石',
    Art: Stone,
    colors: ['#D6976E', '#2A2522', '#3F5F86', '#BFD3B4', '#2E4A6C'],
  },
  silver: {
    name: '岚',
    Art: Silver,
    colors: ['#F5CDB2', '#E4E1E6', '#8E4F6E', '#EFB7B3', '#6E3A55'],
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
