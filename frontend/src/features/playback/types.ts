export interface AvatarSpec {
  schema_version: 1;
  avatar_id: string;
  label: string;
  palette: Record<string, string>;
  mouth_states: 4;
  stylized: true;
}

export interface MediaScript {
  persona_name: string;
  explicit_label: string;
  abstain: boolean;
  segments: { index: number; kind: 'notice' | 'speech'; text: string }[];
  citations: { ref_id: string; reason: string }[];
}

export interface Capabilities {
  available: boolean;
  video?: { available: boolean };
  backend: string | null;
  label: string;
  avatar?: AvatarSpec;
  avatar_model?: { format: 'vrm'; url: string } | null;
  error?: string;
}

export interface AudioPart {
  index: number;
  url: string;
  lipsync: { fps: number; levels: number[] } | null;
}
