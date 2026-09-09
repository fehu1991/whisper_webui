class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super(); this.samples = new Int16Array(4000); this.offset = 0; this.stopped = false; this.levelTicks = 0;
    this.port.onmessage = event => {
      if (event.data === 'stop') {
        if (this.offset) this.send();
        this.stopped = true; this.port.postMessage({type:'flushed'});
      }
    };
  }
  send() {
    const data = this.samples.buffer.slice(0, this.offset * 2);
    this.port.postMessage({type:'audio', data}, [data]); this.offset = 0;
  }
  process(inputs, outputs) {
    if (this.stopped) return false;
    const channels = inputs[0];
    if (!channels?.length) return true;
    let sum = 0;
    for (let i=0; i<channels[0].length; i++) {
      let sample = 0;
      for (const channel of channels) sample += channel[i] || 0;
      sample = Math.max(-1, Math.min(1, sample / channels.length));
      this.samples[this.offset++] = Math.round(sample * (sample < 0 ? 32768 : 32767)); sum += sample * sample;
      if (this.offset === this.samples.length) this.send();
    }
    if (++this.levelTicks % 8 === 0) this.port.postMessage({type:'level', value:Math.sqrt(sum/channels[0].length)});
    return true;
  }
}
registerProcessor('local-capture', CaptureProcessor);
