// Voice session client for WS /api/a/voice.
// Voice mode (Cartesia): mic → 16 kHz PCM16 frames → server (Ink-2); server streams Sonic PCM16 24 kHz back.
// Text mode (Cartesia unreachable): the browser speaks lines (es-MX speechSynthesis) and recognizes speech
// (Web Speech API) or the applicant types. Barge-in: the applicant talking over an interruptible line stops it
// and the server is told which word was playing; locked lines are never cut.
import { wsUrl } from '../api'

export type Line = { id: string; text: string; locked: boolean; kind: string; field: string | null; end_call?: boolean; meta?: any }
export type Caption = { who: 'ellis' | 'usted'; text: string; locked?: boolean; partial?: boolean }
export type VoiceState = 'idle' | 'connecting' | 'speaking' | 'listening' | 'thinking' | 'ended'

type Handlers = {
  onState: (s: VoiceState) => void
  onCaption: (c: Caption) => void
  onPartial: (t: string) => void
  onReady: (info: any) => void
  onLine: (l: Line) => void
  onEnd: () => void
  onError: (msg: string) => void
}

const WORKLET = `
class Mic extends AudioWorkletProcessor {
  process(inputs) { const ch = inputs[0] && inputs[0][0]; if (ch) this.port.postMessage(ch.slice(0)); return true }
}
registerProcessor('ellis-mic', Mic)`

export class VoiceClient {
  ws: WebSocket | null = null
  ctx: AudioContext | null = null
  stream: MediaStream | null = null
  node: AudioWorkletNode | null = null
  sources: AudioBufferSourceNode[] = []
  nextTime = 0
  lineStart: Record<string, number> = {}
  current: Line | null = null
  mode: 'voice' | 'text' = 'text'
  clientTts = false
  recog: any = null
  speakingWord: string | null = null
  pcmBuf: number[] = []
  ended = false
  patient = false
  h: Handlers

  constructor(h: Handlers) {
    this.h = h
  }

  async start(wantVoice: boolean) {
    this.h.onState('connecting')
    // ponytail: request the context at STT's native 16 kHz so the browser's own (band-limited) resampler
    // does the downsampling. The old code ran the context at the device rate (44.1/48 kHz) and then
    // decimated by picking every Nth sample with no anti-aliasing filter, which injected noise into every
    // frame sent to Ink-2 and degraded both transcription accuracy and turn-detection confidence.
    this.ctx = new AudioContext({ sampleRate: 16000 })
    if (wantVoice) {
      // ponytail: getUserMedia can hang forever instead of rejecting (e.g. OS never shows the
      // permission prompt); without a timeout the session would be stuck on "connecting" with no WS.
      const timeout = new Promise<never>((_, reject) => setTimeout(() => reject(new Error('mic_timeout')), 8000))
      try {
        this.stream = await Promise.race([
          navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } }),
          timeout,
        ])
      } catch {
        this.h.onError('mic_denied')
        wantVoice = false
      }
    }
    if (this.ended) { this.stream?.getTracks().forEach((t) => t.stop()); return }
    const ws = new WebSocket(wsUrl('/api/a/voice'))
    this.ws = ws
    ws.onopen = () => ws.send(JSON.stringify({ type: 'start', mode: wantVoice ? 'voice' : 'text' }))
    ws.onmessage = (e) => this.onMessage(JSON.parse(e.data))
    ws.onclose = () => {
      if (!this.ended) this.h.onError('offline')
      this.stop(false)
    }
  }

  private async startMic() {
    if (!this.ctx || !this.stream) return
    const url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }))
    await this.ctx.audioWorklet.addModule(url)
    const src = this.ctx.createMediaStreamSource(this.stream)
    this.node = new AudioWorkletNode(this.ctx, 'ellis-mic')
    const ratio = this.ctx.sampleRate / 16000
    this.node.port.onmessage = (ev) => {
      const f32 = ev.data as Float32Array
      for (let i = 0; i < f32.length; i += ratio) this.pcmBuf.push(f32[Math.floor(i)])
      if (this.pcmBuf.length >= 1600) {
        const n = this.pcmBuf.length
        const out = new Int16Array(n)
        for (let i = 0; i < n; i++) out[i] = Math.max(-1, Math.min(1, this.pcmBuf[i])) * 0x7fff
        this.pcmBuf = []
        if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(out.buffer)
      }
    }
    src.connect(this.node)
  }

  private startRecognition() {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SR || !this.stream) return
    const r = new SR()
    r.lang = 'es-MX'
    r.continuous = true
    r.interimResults = true
    r.onresult = (ev: any) => {
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const res = ev.results[i]
        const t = res[0].transcript.trim()
        if (!t) continue
        if (res.isFinal) this.sendText(t)
        else {
          this.h.onPartial(t)
          // barge-in: two or more words that are not just our own line echoing back
          if (this.current && !this.current.locked && t.split(/\s+/).length >= 2 && !this.current.text.toLowerCase().includes(t.toLowerCase())) this.bargeIn()
        }
      }
    }
    r.onend = () => { if (!this.ended) try { r.start() } catch { /* already started */ } }
    try { r.start() } catch { /* ignore */ }
    this.recog = r
  }

  private onMessage(m: any) {
    switch (m.type) {
      case 'ready':
        this.mode = m.mode
        this.clientTts = m.client_tts
        this.patient = m.patient_mode
        this.h.onReady(m)
        if (this.mode === 'voice') this.startMic()
        else this.startRecognition()
        break
      case 'line': {
        const l: Line = m
        this.current = l
        this.h.onLine(l)
        this.h.onCaption({ who: 'ellis', text: l.text, locked: l.locked })
        if (this.clientTts) this.speakLocally(l)
        break
      }
      case 'audio':
        this.play(m.line_id, m.data)
        break
      case 'line_end':
        if (this.current?.id === m.line_id && !this.clientTts) this.current = null
        break
      case 'stop_audio':
        this.stopAudio(true)
        break
      case 'user_partial':
        this.h.onPartial(m.text)
        break
      case 'user_final':
        this.h.onPartial('')
        this.h.onCaption({ who: 'usted', text: m.text })
        break
      case 'state':
        this.h.onState(m.state)
        break
      case 'end_call':
        this.ended = true
        setTimeout(() => this.stop(true), 4000)
        break
      case 'error':
        this.h.onError(m.message)
        break
    }
  }

  private play(lineId: string, b64: string) {
    if (!this.ctx) return
    const bin = atob(b64)
    const i16 = new Int16Array(bin.length / 2)
    for (let i = 0; i < i16.length; i++) i16[i] = (bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8)) << 16 >> 16
    const buf = this.ctx.createBuffer(1, i16.length, 24000)
    const ch = buf.getChannelData(0)
    for (let i = 0; i < i16.length; i++) ch[i] = i16[i] / 0x8000
    const src = this.ctx.createBufferSource()
    src.buffer = buf
    src.connect(this.ctx.destination)
    const t = Math.max(this.ctx.currentTime + 0.03, this.nextTime)
    if (this.lineStart[lineId] === undefined) this.lineStart[lineId] = t
    src.start(t)
    this.nextTime = t + buf.duration
    this.sources.push(src)
    src.onended = () => { this.sources = this.sources.filter((s) => s !== src) }
  }

  private stopAudio(report: boolean) {
    for (const s of this.sources) try { s.stop() } catch { /* ended */ }
    this.sources = []
    if (this.ctx) this.nextTime = this.ctx.currentTime
    const l = this.current
    if (report && l && this.ctx && this.lineStart[l.id] !== undefined) {
      const pos = (this.ctx.currentTime - this.lineStart[l.id]) * 1000
      this.send({ type: 'interrupt', line_id: l.id, position_ms: Math.max(0, pos) })
    }
  }

  private speakLocally(l: Line) {
    const synth = window.speechSynthesis
    if (!synth) { this.send({ type: 'spoken', line_id: l.id }); return }
    const u = new SpeechSynthesisUtterance(l.text)
    u.lang = 'es-MX'
    u.rate = this.patient ? 0.85 : 1
    const v = synth.getVoices().find((x) => x.lang === 'es-MX') || synth.getVoices().find((x) => x.lang.startsWith('es'))
    if (v) u.voice = v
    u.onboundary = (ev) => {
      const rest = l.text.slice(ev.charIndex)
      this.speakingWord = (rest.match(/^[\p{L}\d]+/u) || [null])[0]
    }
    let started = false
    let finished = false
    const done = () => {
      if (finished) return
      finished = true
      if (this.current?.id === l.id) this.current = null
      this.send({ type: 'spoken', line_id: l.id })
    }
    u.onstart = () => { started = true }
    u.onend = done
    u.onerror = done
    synth.speak(u)
    // No usable voice (or a headless browser): captions only; do not hold the conversation.
    setTimeout(() => { if (!started) { synth.cancel(); done() } }, 1500)
  }

  bargeIn() {
    const l = this.current
    if (!l || l.locked) return
    if (this.clientTts) {
      window.speechSynthesis?.cancel()
      this.send({ type: 'interrupt', line_id: l.id, word: this.speakingWord })
      this.send({ type: 'speech_start' })
      this.current = null
    }
  }

  sendText(text: string) {
    if (this.current && !this.current.locked && this.clientTts) this.bargeIn()
    this.send({ type: 'text', text })
  }

  private send(m: any) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(m))
  }

  endCall() {
    this.send({ type: 'end' })
  }

  stop(notify = true) {
    this.ended = true
    this.stopAudio(false)
    window.speechSynthesis?.cancel()
    try { this.recog?.stop() } catch { /* ignore */ }
    this.node?.disconnect()
    this.stream?.getTracks().forEach((t) => t.stop())
    if (this.ws && this.ws.readyState <= 1) this.ws.close()
    this.ctx?.close().catch(() => undefined)
    this.ctx = null
    this.h.onState('ended')
    if (notify) this.h.onEnd()
  }
}
