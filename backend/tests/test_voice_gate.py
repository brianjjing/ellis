"""Level gate in front of Ink-2: room chatter becomes silence, near-field speech passes with pre-roll."""

import random
from array import array

from ellis.voice.cartesia import Gate


def frame(amp, seed):
    r = random.Random(seed)
    return array("h", (int(r.gauss(0, amp)) for _ in range(1600))).tobytes()


def test_gate():
    g = Gate(margin_db=8)
    room = [g(frame(300, i)) for i in range(50)]  # ~-40 dBFS chatter
    assert not any(room[-1]) and sum(map(any, room)) <= 2
    out = g(frame(3000, 99))  # ~-20 dBFS near-field speech
    assert len(out) == 3 * 3200 and any(out)  # two frames of pre-roll + this one
    after = [g(frame(300, 100 + i)) for i in range(10)]
    assert all(map(any, after[:8])) and not any(after[-1])  # ~800 ms hangover, then shut
    assert len(g(b"\x01\x02\x03")) == 3  # odd-length frame from the client doesn't crash it
