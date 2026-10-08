export interface AvatarSpec {
  schema_version: 1;
  avatar_id: string;
  palette: Record<string, string>;
  mouth_states: 4;
  stylized: true;
}

export interface Capabilities {
  available: boolean;
  video?: { available: boolean; asset_key?: string };
  backend: string | null;
  avatar?: AvatarSpec;
  avatar_preset?: string;
  avatar_presets?: { id: string; name: string }[];
  avatar_model?: { format: 'vrm'; url: string } | null;
  avatar_image?: { url: string } | null;
  error?: string;
}

export interface AudioPart {
  index: number;
  url: string;
  duration_s: number;
  lipsync: { fps: number; levels: number[] } | null;
}
