// Capture only: never connected to audible output. Downsample to 16 kHz PCM16 LE.
class PcmCapture extends AudioWorkletProcessor {
  constructor() {
    super()
    this.phase = 0
    this.sum = 0
    this.count = 0
    this.samples = []
    this.port.onmessage = ({ data }) => {
      if (data === 'flush') {
        this.emit()
        this.port.postMessage({ flushed: true })
      }
    }
  }
  emit() {
    if (!this.samples.length) return
    const bytes = new ArrayBuffer(this.samples.length * 2)
    const view = new DataView(bytes)
    this.samples.forEach((sample, index) => view.setInt16(index * 2, sample, true))
    this.samples = []
    this.port.postMessage({ audio: bytes }, [bytes])
  }
  process(inputs) {
    const input = inputs[0]?.[0]
    if (!input) return true
    const ratio = sampleRate / 16000
    for (const value of input) {
      this.sum += value
      this.count++
      this.phase++
      if (this.phase >= ratio) {
        const sample = Math.max(-1, Math.min(1, this.sum / this.count))
        this.samples.push(Math.round(sample * (sample < 0 ? 32768 : 32767)))
        this.phase -= ratio
        this.sum = 0
        this.count = 0
        if (this.samples.length === 3200) this.emit()
      }
    }
    return true
  }
}
registerProcessor('pcm-capture', PcmCapture)
