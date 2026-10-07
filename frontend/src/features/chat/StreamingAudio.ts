export interface AudioFrame {
  type: number;
  payload: Uint8Array;
}

export class AudioFrameParser {
  private pending = new Uint8Array(0);

  push(chunk: Uint8Array): AudioFrame[] {
    const data = new Uint8Array(this.pending.length + chunk.length);
    data.set(this.pending);
    data.set(chunk, this.pending.length);
    const frames: AudioFrame[] = [];
    let offset = 0;
    while (data.length - offset >= 5) {
      const type = data[offset];
      const length = new DataView(data.buffer).getUint32(offset + 1);
      if (type < 1 || type > 4 || length > 16 * 1024 * 1024)
        throw new Error('无效的语音流');
      if (data.length - offset - 5 < length) break;
      frames.push({
        type,
        payload: data.slice(offset + 5, offset + 5 + length),
      });
      offset += 5 + length;
    }
    this.pending = data.slice(offset);
    return frames;
  }

  finish() {
    if (this.pending.length) throw new Error('语音流不完整');
  }
}

export interface StreamingView {
  loading: boolean;
  speaking: boolean;
  level: number;
  progress: number;
  caption: string;
}

export class StreamingAudio {
  private analyser: AnalyserNode;
  private samples = new Float32Array(512);
  private queued: AudioBuffer[] = [];
  private sources = new Set<AudioBufferSourceNode>();
  private captions: { time: number; text: string }[] = [];
  private rate = 0;
  private segments = 1;
  private received = 0;
  private scheduled = 0;
  private end = 0;
  private origin = 0;
  private base = 0;
  private waiting = true;
  private paused = false;
  private stopped = false;
  private ended = false;
  private animation: number | null = null;
  hasAudio = false;

  constructor(
    private context: AudioContext,
    private change: (view: StreamingView) => void,
    private complete: () => void,
  ) {
    this.analyser = context.createAnalyser();
    this.analyser.fftSize = this.samples.length;
    this.analyser.connect(context.destination);
    context.addEventListener('statechange', this.tick);
    this.tick();
  }

  accept(frame: AudioFrame) {
    if (this.stopped || this.ended) throw new Error('无效的语音流');
    if (frame.type !== 2) {
      const meta = JSON.parse(new TextDecoder().decode(frame.payload));
      if (frame.type === 4)
        throw new Error(meta.detail || '语音暂不可用，请重试');
      if (!meta || typeof meta !== 'object')
        throw new Error('无效的语音元数据');
      if (frame.type === 3) {
        if (!Number.isFinite(meta.duration_s) || meta.duration_s < 0)
          throw new Error('无效的语音时长');
        if (!this.hasAudio) throw new Error('没有可播放的语音');
        this.ended = true;
      } else if ('sample_rate' in meta) {
        if (
          this.rate ||
          !Number.isInteger(meta.sample_rate) ||
          meta.sample_rate < 8000 ||
          meta.sample_rate > 192000 ||
          !Number.isInteger(meta.segments) ||
          meta.segments < 0
        )
          throw new Error('无效的语音采样率');
        this.rate = meta.sample_rate;
        this.segments = Math.max(1, meta.segments);
      } else {
        if (
          !this.rate ||
          !Number.isInteger(meta.segment) ||
          meta.segment < 0 ||
          typeof meta.caption !== 'string'
        )
          throw new Error('无效的语音字幕');
        this.captions.push({ time: this.received, text: meta.caption });
      }
    } else {
      if (!this.rate || !frame.payload.length || frame.payload.length % 2)
        throw new Error('无效的语音数据');
      const count = frame.payload.length / 2;
      const buffer = this.context.createBuffer(1, count, this.rate);
      const pcm = new DataView(
        frame.payload.buffer,
        frame.payload.byteOffset,
        frame.payload.byteLength,
      );
      const samples = buffer.getChannelData(0);
      for (let index = 0; index < count; index++)
        samples[index] = pcm.getInt16(index * 2, true) / 32768;
      this.queued.push(buffer);
      this.received += buffer.duration;
      this.hasAudio = true;
    }
    this.schedule();
  }

  private schedule() {
    if (this.stopped || this.paused || this.context.state !== 'running') return;
    if (!this.waiting && this.context.currentTime >= this.end)
      this.waiting = true;
    const duration = this.queued.reduce(
      (sum, buffer) => sum + buffer.duration,
      0,
    );
    if (this.waiting) {
      if (!duration || (!this.ended && duration < 0.15)) return;
      this.base = this.scheduled;
      this.origin = this.context.currentTime + 0.015;
      this.end = this.origin;
      this.waiting = false;
    }
    for (const buffer of this.queued.splice(0)) {
      const source = this.context.createBufferSource();
      source.buffer = buffer;
      source.connect(this.analyser);
      source.start(this.end);
      this.end += buffer.duration;
      this.scheduled += buffer.duration;
      this.sources.add(source);
      source.onended = () => {
        this.sources.delete(source);
        source.disconnect();
        if (!this.sources.size) {
          this.waiting = true;
          if (this.ended && !this.queued.length) this.finish();
          else this.schedule();
        }
      };
    }
  }

  private elapsed() {
    return this.waiting
      ? this.scheduled
      : Math.min(
          this.scheduled,
          this.base + Math.max(0, this.context.currentTime - this.origin),
        );
  }

  private tick = () => {
    if (this.stopped) return;
    if (this.animation !== null) cancelAnimationFrame(this.animation);
    this.schedule();
    const elapsed = this.elapsed();
    const speaking =
      !this.paused &&
      !this.waiting &&
      this.context.state === 'running' &&
      this.context.currentTime >= this.origin;
    this.analyser.getFloatTimeDomainData(this.samples);
    const rms = Math.sqrt(
      this.samples.reduce((sum, value) => sum + value * value, 0) /
        this.samples.length,
    );
    const estimate = this.ended
      ? this.received
      : (this.received * this.segments) / Math.max(1, this.captions.length);
    this.change({
      loading:
        !this.paused && (this.waiting || this.context.state !== 'running'),
      speaking,
      level: speaking ? Math.min(3, rms * 12) : 0,
      progress: estimate
        ? Math.min(this.ended ? 1 : 0.99, elapsed / estimate)
        : 0,
      caption: speaking
        ? (this.captions.filter((caption) => caption.time <= elapsed).at(-1)
            ?.text ?? '')
        : '',
    });
    if (this.ended && this.waiting && !this.queued.length && !this.paused)
      return this.finish();
    this.animation = requestAnimationFrame(this.tick);
  };

  private finish() {
    this.stop();
    this.complete();
  }

  async resume() {
    this.paused = false;
    await this.context.resume();
    if (!this.stopped) this.tick();
  }

  pause() {
    this.paused = true;
    this.tick();
    return this.context.suspend();
  }

  stop() {
    this.stopped = true;
    if (this.animation !== null) cancelAnimationFrame(this.animation);
    this.context.removeEventListener('statechange', this.tick);
    for (const source of this.sources) {
      source.onended = null;
      source.stop();
      source.disconnect();
    }
    this.sources.clear();
    this.queued = [];
    this.analyser.disconnect();
  }
}

export async function readAudioStream(
  response: Response,
  player: StreamingAudio,
) {
  if (
    !response.body ||
    !response.headers
      .get('content-type')
      ?.startsWith('application/octet-stream')
  )
    throw new Error('语音流不可用');
  const reader = response.body.getReader();
  const parser = new AudioFrameParser();
  let ended = false;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const frame of parser.push(value)) {
        player.accept(frame);
        if (frame.type === 3) ended = true;
      }
    }
    parser.finish();
    if (!ended) throw new Error('语音流不完整');
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
