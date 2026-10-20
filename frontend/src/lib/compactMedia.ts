/** Making a recording smaller in the browser before it is uploaded, for material that only feeds memories:
 * uncompressed or lossless audio (wav, flac…) becomes Opus, and with `videoAudio` the sound of an MP4/MOV video is
 * taken out as it is (no re-encoding). Whatever cannot be done here (an old browser, another container, a file
 * that would not get smaller) is uploaded unchanged. Voice samples for speech synthesis never come through here. */

export type Compaction = 'audio' | 'audio-and-video';

const OPUS = { codec: 'opus', numberOfChannels: 1, bitrate: 32_000 } as const;
const VIDEO_EXTENSIONS = new Set(['mp4', 'mov', 'm4v']);
const AUDIO_EXTENSIONS = new Set(['wav', 'flac']);
// Seconds between 1904-01-01 (the MP4 epoch) and 1970-01-01.
const MP4_EPOCH_OFFSET = 2_082_844_800;

const extension = (name: string) => name.split('.').at(-1)?.toLowerCase() ?? '';

/** Whether `compactMedia` may change this file at all (so callers know a conversion step will show). */
export function compactable(file: File, mode: Compaction): boolean {
  const ext = extension(file.name);
  return (
    AUDIO_EXTENSIONS.has(ext) ||
    (mode === 'audio-and-video' && VIDEO_EXTENSIONS.has(ext))
  );
}

/** The smaller upload for `file`, or `file` itself when nothing smaller can be made. `progress` gets 0..1. */
export async function compactMedia(
  file: File,
  mode: Compaction,
  signal: AbortSignal,
  progress: (done: number) => void,
): Promise<File> {
  if (!compactable(file, mode) || typeof AudioEncoder === 'undefined')
    return file;
  const media = await import('mediabunny');
  const input = new media.Input({
    source: new media.BlobSource(file),
    formats: [media.MP4, media.QTFF, media.WAVE, media.FLAC],
  });
  try {
    const audio = await input.getPrimaryAudioTrack();
    if (!audio) return file;
    const video = await input.getPrimaryVideoTrack();
    const uncompressed =
      audio.codec === 'flac' ||
      (media.PCM_AUDIO_CODECS as readonly string[]).includes(audio.codec ?? '');
    if (video && mode !== 'audio-and-video') return file;
    if (!video && !uncompressed) return file;
    if (uncompressed && !(await media.canEncodeAudio('opus', OPUS)))
      return file;
    const created = video
      ? await mp4CreationTime(file)
      : dateToMp4((await input.getMetadataTags()).date);
    const target = new media.BufferTarget();
    const output = new media.Output({
      format: new media.Mp4OutputFormat({ fastStart: 'in-memory' }),
      target,
    });
    const conversion = await media.Conversion.init({
      input,
      output,
      video: { discard: true },
      audio: uncompressed ? { ...OPUS, forceTranscode: true } : {},
      tags: {},
      showWarnings: false,
    });
    if (!conversion.isValid) return file;
    conversion.onProgress = (done) => progress(done);
    const cancel = () => void conversion.cancel();
    signal.addEventListener('abort', cancel, { once: true });
    try {
      await conversion.execute();
    } finally {
      signal.removeEventListener('abort', cancel);
    }
    signal.throwIfAborted();
    const buffer = target.buffer;
    if (!buffer || buffer.byteLength >= file.size * 0.9) return file;
    // The muxer stamps "now"; the original's time keeps the recording's date and makes the bytes repeatable.
    setMp4CreationTime(new Uint8Array(buffer), created);
    const stem = file.name.replace(/\.[^.]*$/u, '');
    return new File([buffer], `${stem}.m4a`, {
      type: 'audio/mp4',
      lastModified: file.lastModified,
    });
  } catch (error) {
    signal.throwIfAborted();
    // Unreadable here is not unreadable on the server: send the original.
    console.warn('compactMedia: uploading the original', error);
    return file;
  } finally {
    input.dispose();
  }
}

function dateToMp4(date: Date | undefined): number {
  if (!date || Number.isNaN(date.getTime())) return 0;
  return Math.max(0, Math.floor(date.getTime() / 1000) + MP4_EPOCH_OFFSET);
}

interface Box {
  type: string;
  start: number;
  header: number;
  size: number;
}

/** The boxes in `data[from, to)`. */
function boxes(data: DataView, from: number, to: number): Box[] {
  const found: Box[] = [];
  let at = from;
  while (at + 8 <= to) {
    let size = data.getUint32(at);
    let header = 8;
    const type = String.fromCharCode(
      data.getUint8(at + 4),
      data.getUint8(at + 5),
      data.getUint8(at + 6),
      data.getUint8(at + 7),
    );
    if (size === 1) {
      if (at + 16 > to) break;
      size = Number(data.getBigUint64(at + 8));
      header = 16;
    } else if (size === 0) size = to - at;
    if (size < header || at + size > to) break;
    found.push({ type, start: at, header, size });
    at += size;
  }
  return found;
}

/** The creation time in an MP4/MOV's `mvhd`, in seconds since 1904 (0 when absent), read without loading the
 * media data: only box headers and the `moov` box are read. */
export async function mp4CreationTime(file: Blob): Promise<number> {
  let at = 0;
  while (at + 8 <= file.size) {
    const head = new DataView(await file.slice(at, at + 16).arrayBuffer());
    let size = head.getUint32(0);
    let header = 8;
    if (size === 1 && head.byteLength >= 16) {
      size = Number(head.getBigUint64(8));
      header = 16;
    } else if (size === 0) size = file.size - at;
    if (size < header) return 0;
    const type = String.fromCharCode(
      ...new Uint8Array(head.buffer, 4, 4).values(),
    );
    if (type === 'moov') {
      if (size > 256 * 1024 ** 2) return 0;
      const moov = new DataView(await file.slice(at, at + size).arrayBuffer());
      const mvhd = boxes(moov, header, moov.byteLength).find(
        (box) => box.type === 'mvhd',
      );
      if (!mvhd) return 0;
      const body = mvhd.start + mvhd.header;
      return moov.getUint8(body) === 1
        ? Number(moov.getBigUint64(body + 4))
        : moov.getUint32(body + 4);
    }
    at += size;
  }
  return 0;
}

/** Write `seconds` (since 1904) as the creation and modification time of every `mvhd`, `tkhd` and `mdhd` box. */
export function setMp4CreationTime(bytes: Uint8Array, seconds: number) {
  const data = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const visit = (from: number, to: number) => {
    for (const box of boxes(data, from, to)) {
      const body = box.start + box.header;
      if (['moov', 'trak', 'mdia'].includes(box.type))
        visit(body, box.start + box.size);
      else if (['mvhd', 'tkhd', 'mdhd'].includes(box.type)) {
        if (data.getUint8(body) === 1) {
          data.setBigUint64(body + 4, BigInt(seconds));
          data.setBigUint64(body + 12, BigInt(seconds));
        } else {
          const value = seconds <= 0xffffffff ? seconds : 0;
          data.setUint32(body + 4, value);
          data.setUint32(body + 8, value);
        }
      }
    }
  };
  visit(0, bytes.byteLength);
}
