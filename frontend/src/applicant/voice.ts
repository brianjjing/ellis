// Voice session client for WS /api/a/voice. One session per chat, whatever the input mode: typing and talking
// share it, so switching never restarts the conversation. Ellis always speaks with Cartesia's voice (Sonic PCM16
// 24 kHz from the server); with Cartesia unreachable, lines are captions only, never the browser's own voice.
// Push to talk: the mic streams silence until hold() and real audio until just after release(), through a level gate
// (gate.ts) that silences what isn't clearly the applicant's voice; the server keeps only what was said while held and
// submits it on release. Holding also cuts Ellis off at any point in any line.
import { wsUrl } from '../api'
import { Gate } from './gate'

// ponytail: people let go a beat before their last word ends, so the mic stays open this much longer (the gate still
// silences the room). Raise it if last words get clipped.
const RELEASE_TAIL_MS = 300

export type Line = { id: string; text: string; locked: boolean; kind: string; field: string | null; end_call?: boolean; meta?: any }
export type Caption = { who: 'ellis' | 'usted'; text: string; spoken?: boolean }
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
  current: Line | null = null
  muted: string | null = null // a line the applicant talked over: its late audio chunks are dropped
  mode: 'voice' | 'text' = 'text'
  talking = false
  releasing: ReturnType<typeof setTimeout> | null = null
  soundOn = true // Ellis's voice on/off (the mute button); muted lines still arrive as text
  voice = true // talking vs. typing, sent with start and on every switch
  pcmBuf: number[] = []
  energy = 0 // sum of squares of this frame's real samples, button up or down: the gate's level
  gate = new Gate()
  ended = false
  h: Handlers

  constructor(h: Handlers) {
    this.h = h
  }

  async start(lang: string = 'en', locale: string = 'en-US') {
    this.h.onState('connecting')
    // ponytail: request the context at STT's native 16 kHz so the browser's own (band-limited) resampler
    // does the downsampling instead of naive decimation.
    this.ctx = new AudioContext({ sampleRate: 16000 })
    // ponytail: getUserMedia can hang forever instead of rejecting (e.g. OS never shows the permission
    // prompt); without a timeout the session would be stuck on "connecting" with no WS.
    const timeout = new Promise<never>((_, reject) => setTimeout(() => reject(new Error('mic_timeout')), 8000))
    try {
      this.stream = await Promise.race([
        // no autoGainControl: it turns the room up whenever you pause, shrinking the level gap the gate relies on
        navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: false, channelCount: 1 } }),
        timeout,
      ])
    } catch {
      this.h.onError('mic_denied') // Ellis still speaks; the applicant types
    }
    if (this.ended) { this.stream?.getTracks().forEach((t) => t.stop()); return }
    const ws = new WebSocket(wsUrl('/api/a/voice'))
    this.ws = ws
    ws.onopen = () => ws.send(JSON.stringify({ type: 'start', voice: this.voice, language: lang, locale }))
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
      // silence unless the button is held: the STT socket stays fed, but nothing said off-button leaves the browser
      for (let i = 0; i < f32.length; i += ratio) {
        const x = f32[Math.floor(i)]
        this.energy += x * x
        this.pcmBuf.push(this.talking ? x : 0)
      }
      if (this.pcmBuf.length >= 1600) this.flush()
    }
    src.connect(this.node)
  }

  private flush() {
    const n = this.pcmBuf.length
    if (!n) return
    const db = 10 * Math.log10(this.energy / n + 1e-12)
    let pcm = this.pcmBuf
    this.pcmBuf = []
    this.energy = 0
    if (this.talking) pcm = this.gate.pass(pcm, db)
    else this.gate.heard(db, this.sources.length > 0)
    const out = new Int16Array(pcm.length)
    for (let i = 0; i < pcm.length; i++) out[i] = Math.max(-1, Math.min(1, pcm[i])) * 0x7fff
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(out.buffer)
  }

  private onMessage(m: any) {
    switch (m.type) {
      case 'ready':
        this.mode = m.mode
        this.h.onReady(m)
        if (this.mode === 'voice') this.startMic()
        break
      case 'line': {
        const l: Line = m
        this.current = l
        this.h.onLine(l)
        this.h.onCaption({ who: 'ellis', text: l.text })
        break
      }
      case 'audio':
        if (this.soundOn && m.line_id !== this.muted) this.play(m.line_id, m.data)
        break
      case 'line_end':
        if (this.current?.id === m.line_id) this.current = null
        break
      case 'stop_audio':
        this.stopAudio()
        break
      case 'user_partial':
        this.h.onPartial(m.text)
        break
      case 'user_final':
        this.h.onPartial('')
        this.h.onCaption({ who: 'usted', text: m.text, spoken: m.spoken })
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
    src.start(t)
    this.nextTime = t + buf.duration
    this.sources.push(src)
    src.onended = () => { this.sources = this.sources.filter((s) => s !== src) }
  }

  private stopAudio() {
    for (const s of this.sources) try { s.stop() } catch { /* ended */ }
    this.sources = []
    if (this.ctx) this.nextTime = this.ctx.currentTime
  }

  // Push to talk. Holding cuts Ellis off right away, wherever it is in a line.
  hold(): boolean {
    if (!this.stream || !this.ctx) return false
    if (this.releasing) { // pressed again within the tail: the same turn goes on
      clearTimeout(this.releasing)
      this.releasing = null
      return true
    }
    this.ctx.resume()
    this.muted = this.current?.id ?? null
    this.stopAudio()
    this.talking = true
    this.send({ type: 'talk', down: true })
    return true
  }

  release() {
    if (!this.talking || this.releasing) return
    this.releasing = setTimeout(() => {
      this.releasing = null
      this.flush() // while still held, so the last frame goes through the gate too
      this.talking = false
      this.send({ type: 'talk', down: false })
    }, RELEASE_TAIL_MS)
  }

  setSound(on: boolean) {
    this.soundOn = on
    if (!on) this.stopAudio()
  }

  // Typing or talking: only tells the server whether silence means "gone" (it doesn't while typing).
  setVoice(voice: boolean) {
    this.voice = voice
    if (!voice) this.release()
    this.send({ type: 'mode', voice })
  }

  sendText(text: string) {
    this.muted = this.current?.id ?? null
    this.stopAudio()
    this.send({ type: 'text', text })
  }

  // The applicant's answer to a permission card (a setting change, a question for the clinic).
  permission(id: string, allow: boolean) {
    this.send({ type: 'permission', id, allow })
  }

  private send(m: any) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(m))
  }

  endCall() {
    this.send({ type: 'end' })
  }

  stop(notify = true) {
    this.ended = true
    this.stopAudio()
    this.node?.disconnect()
    this.stream?.getTracks().forEach((t) => t.stop())
    if (this.ws && this.ws.readyState <= 1) this.ws.close()
    this.ctx?.close().catch(() => undefined)
    this.ctx = null
    this.h.onState('ended')
    if (notify) this.h.onEnd()
  }
}
