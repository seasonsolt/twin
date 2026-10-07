export class GaplessAudio {
  readonly context: AudioContext;
  private analyser: AnalyserNode;
  private samples = new Float32Array(512);
  private sources = new Map<
    string,
    { source: AudioBufferSourceNode; start: number }
  >();
  private end = 0;

  constructor() {
    const Constructor =
      globalThis.AudioContext ??
      (window as typeof window & { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!Constructor) throw new Error('Web Audio 不可用');
    this.context = new Constructor();
    this.analyser = this.context.createAnalyser();
    this.analyser.fftSize = this.samples.length;
    this.analyser.connect(this.context.destination);
  }

  level() {
    this.analyser.getFloatTimeDomainData(this.samples);
    const rms = Math.sqrt(
      this.samples.reduce((sum, value) => sum + value * value, 0) /
        this.samples.length,
    );
    return Math.min(3, rms * 12);
  }

  resume() {
    return this.context.resume();
  }
  pause() {
    return this.context.suspend();
  }
  decode(data: ArrayBuffer) {
    return this.context.decodeAudioData(data);
  }
  has(key: string) {
    return this.sources.has(key);
  }
  elapsed(key: string) {
    const item = this.sources.get(key);
    return item ? Math.max(0, this.context.currentTime - item.start) : 0;
  }
  schedule(key: string, buffer: AudioBuffer, onEnded: () => void) {
    if (this.sources.has(key)) return;
    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.analyser);
    const start = Math.max(this.end, this.context.currentTime);
    this.end = start + buffer.duration;
    this.sources.set(key, { source, start });
    source.onended = () => {
      this.sources.delete(key);
      source.disconnect();
      onEnded();
    };
    source.start(start);
  }
  reset() {
    for (const { source } of this.sources.values()) {
      source.onended = null;
      source.stop();
      source.disconnect();
    }
    this.sources.clear();
    this.end = 0;
  }
  close() {
    this.reset();
    this.analyser.disconnect();
    return this.context.close();
  }
}
