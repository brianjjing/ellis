// The push-to-talk level gate (src/applicant/gate.ts). Run: node --experimental-strip-types e2e/gate.check.ts
import assert from 'node:assert/strict'
import { Gate } from '../src/applicant/gate.ts'

const f = (v = 0.01) => new Array(1600).fill(v)
const silent = (out: number[]) => out.every((x) => x === 0)

// Nothing heard yet: nothing is gated.
assert.ok(!silent(new Gate().pass(f(), -60)))

// The room's base loudness ignores a sneeze, Ellis's own voice, and you chatting with the button up (a median
// would follow the chat and then cut you off).
const g = new Gate()
for (let i = 0; i < 40; i++) g.heard(-45, false)
for (let i = 0; i < 3; i++) g.heard(-5, false)
for (let i = 0; i < 250; i++) g.heard(-10, true)
for (let i = 0; i < 50; i++) g.heard(-25, false)
assert.ok(silent(g.pass(f(), -40))) // chatter 5 dB over the room: silence, kept as pre-roll
assert.ok(silent(g.pass(f(), -40)))
const you = g.pass(f(0.1), -25)
assert.equal(you.length, 3 * 1600) // you, with ~200 ms of pre-roll in front
for (let i = 0; i < 5; i++) assert.ok(!silent(g.pass(f(), -40))) // ~500 ms hangover through the gaps between words
assert.ok(silent(g.pass(f(), -40))) // then shut again

// A room nearly as loud as you: once ~1 s of your voice is known, the bar drops under it instead of cutting you off.
const loud = new Gate()
for (let i = 0; i < 40; i++) loud.heard(-30, false)
for (let i = 0; i < 10; i++) assert.ok(silent(loud.pass(f(), -26)))
assert.equal(loud.pass(f(0.1), -26).length, 3 * 1600)

// Close mic: a neighbour well above the room but 25 dB under you is someone farther away.
const near = new Gate()
for (let i = 0; i < 40; i++) near.heard(-55, false)
for (let i = 0; i < 11; i++) near.pass(f(), -15)
for (let i = 0; i < 6; i++) near.pass(f(), -55)
assert.ok(silent(near.pass(f(), -40)))

console.log('gate ok')
