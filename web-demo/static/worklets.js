// Duet web demo — audio worklets. The AudioContext runs at 24 kHz, so one
// Mimi frame = 1920 samples = 80 ms, and no resampling happens anywhere.

class MicProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buf = new Float32Array(1920);
    this.n = 0;
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.buf[this.n++] = ch[i];
      if (this.n === 1920) {
        this.port.postMessage(this.buf.slice(0));
        this.n = 0;
      }
    }
    return true;
  }
}
registerProcessor("mic-processor", MicProcessor);

class PlayerProcessor extends AudioWorkletProcessor {
  // Jitter buffer: if the model occasionally misses its 80 ms budget, playing
  // frames the instant they arrive turns that jitter into audible stutter.
  // Instead we hold playback until PREBUFFER frames (~320 ms) are queued, and
  // re-arm after an underrun — smoothness for a small, constant delay.
  constructor() {
    super();
    this.PREBUFFER = 4;
    this.chunks = [];
    this.cur = null;
    this.idx = 0;
    this.armed = false;
    this.port.onmessage = (e) => {
      this.chunks.push(e.data);
      if (this.chunks.length > 30) this.chunks.shift(); // ~2.4 s cap: stay live, drop backlog
    };
  }
  process(_inputs, outputs) {
    const out = outputs[0][0];
    if (!this.armed && !this.cur) {
      if (this.chunks.length >= this.PREBUFFER) this.armed = true;
      else { out.fill(0); this.port.postMessage(0); return true; }
    }
    let energy = 0;
    for (let i = 0; i < out.length; i++) {
      if (!this.cur || this.idx >= this.cur.length) {
        this.cur = this.chunks.shift() || null;
        this.idx = 0;
        if (!this.cur) this.armed = false; // underrun → re-arm prebuffer
      }
      const s = this.cur ? this.cur[this.idx++] : 0;
      out[i] = s;
      energy += s * s;
    }
    this.port.postMessage(Math.sqrt(energy / out.length));
    return true;
  }
}
registerProcessor("player-processor", PlayerProcessor);
