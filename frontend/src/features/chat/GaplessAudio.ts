export class GaplessAudio {
  private context = new AudioContext();
  private sources = new Map<
    string,
    { source: AudioBufferSourceNode; start: number }
  >();
  private end = 0;

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
    source.connect(this.context.destination);
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
    return this.context.close();
  }
}
