// Level gate between the mic and Ink-2, for push to talk. Ink-2 transcribes any speech it hears while the button is
// held, so frames that aren't clearly the applicant's voice go out as silence (zeros, not gaps: the STT socket wants a
// continuous stream). Both references are percentiles over the last ~20 s, never one moment's level, so a sneeze, a
// shout or a burst of chatter doesn't move them:
// - the room: frames heard with the button up (they never leave the browser) while Ellis is quiet. A frame has to be
//   GATE_DB above its 20th percentile, which also stays put while you chat with the button up.
// - your voice: frames heard with the button held, once there's ~1 s of them. It's the proximity cue one mic gives
//   (loudness falls ~6 dB per doubling of distance): anything FAR_DB under your voice is someone farther away, and the
//   bar never sits within NEAR_DB of your voice, so a room nearly as loud as you gets less gating, not your words cut.
// ponytail: energy only. Ceiling: a neighbour as loud as you at the mic still gets through; a close mic is the fix, a
// speaker-isolation model (e.g. ai-coustics Voice Focus) the upgrade.

export const GATE_DB = 10 // calibration knob: lower it if your own words get cut, raise it if chatter gets through
const FAR_DB = 20
const NEAR_DB = 6
const WINDOW = 200 // frames, ~20 s
const HANG = 5 // frames (~500 ms) kept open after a loud one, through the gaps between words
const PREROLL = 2 // frames (~200 ms) sent ahead of the one that opens it, so soft onsets ("s", "f", "h") survive

const pct = (xs: number[], p: number) => [...xs].sort((a, b) => a - b)[Math.floor(p * (xs.length - 1))]
const keep = (xs: number[], x: number) => { xs.push(x); if (xs.length > WINDOW) xs.shift() }

export class Gate {
  room: number[] = [] // frame levels, dBFS
  voice: number[] = []
  pre: number[][] = []
  hang = 0

  // A frame heard with the button up.
  heard(db: number, ellisPlaying: boolean) {
    if (!ellisPlaying) keep(this.room, db) // Ellis's voice coming back through the mic isn't the room
    this.pre = []
    this.hang = 0
  }

  // A frame heard with the button held: what Ink-2 gets instead.
  pass(frame: number[], db: number): number[] {
    let bar = this.room.length >= 10 ? pct(this.room, 0.2) + GATE_DB : -Infinity // under ~1 s of room heard: open
    if (this.voice.length >= 10) { // before that, a cough or the lead-in chatter would be "your voice"
      const you = pct(this.voice, 0.8)
      bar = Math.min(Math.max(bar, you - FAR_DB), you - NEAR_DB)
    }
    keep(this.voice, db)
    if (db > bar) {
      const out = [...this.pre.flat(), ...frame]
      this.pre = []
      this.hang = HANG
      return out
    }
    if (this.hang > 0) {
      this.hang--
      return frame
    }
    this.pre = [...this.pre, frame].slice(-PREROLL)
    return frame.map(() => 0)
  }
}
