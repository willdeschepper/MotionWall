// Exercise the actual clock against 60/120/144 Hz displays without a DOM.
import fs from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";
const source = fs.readFileSync(new URL("../motionwall/web/player.js", import.meta.url), "utf8");
const clockCode = source.slice(source.indexOf("  function vectorClock("), source.indexOf("  function gifEngine("));
for (const refresh of [60, 120, 144]) {
  for (const fps of [15, 30, 60]) {
    let queue = new Map(), id = 0, timeline = 0, paints = 0;
    const context = vm.createContext({ settings: { fps, speed: 2 },
      requestAnimationFrame: callback => { queue.set(++id, callback); return id; },
      cancelAnimationFrame: key => queue.delete(key) });
    const make = vm.runInContext(clockCode + "\nvectorClock", context);
    const clock = make(delta => { timeline += delta; paints++; });
    clock.play();
    for (let frame = 0; frame <= refresh * 2; frame++) {
      const callbacks = [...queue.values()]; queue.clear();
      callbacks.forEach(callback => callback(frame * 1000 / refresh));
    }
    assert(paints <= fps * 2 + 2, `Exceeded ${fps} fps on ${refresh} Hz: ${paints}`);
    assert(paints >= fps * 2 - 2, `Undershot ${fps} fps: ${paints}`);
    assert(Math.abs(timeline - 4) < .15, `Frame cap altered speed: ${timeline}`);
    clock.pause();
    assert.equal(queue.size, 0, "Pause retained a frame callback");
    clock.play();
    const before = timeline;
    const callbacks = [...queue.values()]; queue.clear();
    callbacks.forEach(callback => callback(100000));
    assert(Math.abs(timeline - before) < .15, "Resume caught up paused wall time");
    clock.pause();
  }
}
console.log("VECTOR CLOCK PASS: bounded paints, real-time speed, pause/resume on 60/120/144 Hz");
