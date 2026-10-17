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
    colors: ['#F3C4A2', '#4A2E26', '#24364F', '#D5E0EE', '#1F5FBF'],
  },
  wave: {
    name: '澜',
    Art: Wave,
    colors: ['#F6C8A4', '#3B2A24', '#3A4250', '#DCE3EA', '#4A6F9C'],
  },
  bun: {
    name: '禾',
    Art: Bun,
    colors: ['#EDB48C', '#2C2320', '#6B7A8F', '#E1E5EA', '#56657A'],
  },
  stone: {
    name: '石',
    Art: Stone,
    colors: ['#D6976E', '#2A2522', '#2F3A48', '#D3DCE6', '#8C2F39'],
  },
  silver: {
    name: '岚',
    Art: Silver,
    colors: ['#F5CDB2', '#D9DBE0', '#3D4F6B', '#CDD5E1', '#2F3F57'],
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
