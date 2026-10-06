export interface AvatarSpec {
  schema_version: 1;
  avatar_id: string;
  label: string;
  palette: Record<string, string>;
  mouth_states: 4;
  stylized: true;
}

export interface Capabilities {
  available: boolean;
  video?: { available: boolean };
  backend: string | null;
  label: string;
  avatar?: AvatarSpec;
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
