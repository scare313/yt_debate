// Sound effects synthesized with Web Audio: no sound files needed, and OBS records them
// together with the debate audio. Disabled with ?nosfx.
const SFX = (() => {
  let ctx = null, out = null, room = null;
  const enabled = !new URLSearchParams(location.search).has("nosfx");

  function noiseBuffer(seconds, color = "white") {
    const len = Math.floor(ctx.sampleRate * seconds);
    const buf = ctx.createBuffer(1, len, ctx.sampleRate);
    const d = buf.getChannelData(0);
    let last = 0;
    for (let i = 0; i < len; i++) {
      const w = Math.random() * 2 - 1;
      last = color === "brown" ? (last + 0.02 * w) / 1.02 : w;
      d[i] = color === "brown" ? last * 3.5 : w;
    }
    return buf;
  }

  function env(gainNode, t0, peak, attack, release) {
    const g = gainNode.gain;
    g.setValueAtTime(0.0001, t0);
    g.exponentialRampToValueAtTime(peak, t0 + attack);
    g.exponentialRampToValueAtTime(0.0001, t0 + attack + release);
  }

  return {
    init(audioCtx, roomTone) {
      if (!enabled || ctx) return;
      ctx = audioCtx;
      out = ctx.createGain();
      out.gain.value = 0.9;
      out.connect(ctx.destination);
      if (roomTone) {
        // Quiet studio room tone so the gaps between lines aren't dead silent.
        const src = ctx.createBufferSource();
        src.buffer = noiseBuffer(4, "brown");
        src.loop = true;
        const bp = ctx.createBiquadFilter();
        bp.type = "lowpass"; bp.frequency.value = 900;
        room = ctx.createGain();
        room.gain.value = 0.05;
        src.connect(bp).connect(room).connect(out);
        src.start();
      }
    },

    whoosh() {
      if (!ctx) return;
      const t = ctx.currentTime, src = ctx.createBufferSource(), bp = ctx.createBiquadFilter(), g = ctx.createGain();
      src.buffer = noiseBuffer(0.4);
      bp.type = "bandpass"; bp.Q.value = 1.2;
      bp.frequency.setValueAtTime(300, t);
      bp.frequency.exponentialRampToValueAtTime(3500, t + 0.3);
      env(g, t, 0.35, 0.08, 0.28);
      src.connect(bp).connect(g).connect(out);
      src.start(t);
    },

    ding() {
      if (!ctx) return;
      const t = ctx.currentTime;
      for (const [f, v] of [[1318, 0.18], [1976, 0.08]]) {
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.type = "sine"; o.frequency.value = f;
        env(g, t, v, 0.005, 0.7);
        o.connect(g).connect(out);
        o.start(t); o.stop(t + 0.8);
      }
    },

    boom() {
      if (!ctx) return;
      const t = ctx.currentTime, o = ctx.createOscillator(), g = ctx.createGain();
      o.type = "sine";
      o.frequency.setValueAtTime(110, t);
      o.frequency.exponentialRampToValueAtTime(38, t + 0.5);
      env(g, t, 0.6, 0.01, 0.6);
      o.connect(g).connect(out);
      o.start(t); o.stop(t + 0.7);
    },

    // Crowd "ooooh": a few detuned voices through a vowel-like filter, gliding down.
    ooh() {
      if (!ctx) return;
      const t = ctx.currentTime, bp = ctx.createBiquadFilter(), g = ctx.createGain();
      bp.type = "bandpass"; bp.frequency.value = 650; bp.Q.value = 3;
      env(g, t, 0.16, 0.25, 1.1);
      bp.connect(g).connect(out);
      for (const base of [196, 247, 294, 330, 392]) {
        const o = ctx.createOscillator();
        o.type = "sawtooth";
        o.frequency.setValueAtTime(base * 1.12, t);
        o.frequency.exponentialRampToValueAtTime(base * 0.92, t + 1.3);
        o.detune.value = (Math.random() - 0.5) * 30;
        o.connect(bp);
        o.start(t); o.stop(t + 1.5);
      }
    },

    // Applause: lots of tiny random claps.
    applause(seconds = 2.8) {
      if (!ctx) return;
      const len = Math.floor(ctx.sampleRate * seconds);
      const buf = ctx.createBuffer(1, len, ctx.sampleRate);
      const d = buf.getChannelData(0);
      const claps = Math.floor(seconds * 55);
      for (let c = 0; c < claps; c++) {
        const start = Math.floor(Math.random() * (len - 2000));
        const amp = 0.4 + Math.random() * 0.6;
        for (let k = 0; k < 900; k++) d[start + k] += (Math.random() * 2 - 1) * amp * Math.exp(-k / 140);
      }
      const src = ctx.createBufferSource(), hp = ctx.createBiquadFilter(), g = ctx.createGain();
      src.buffer = buf;
      hp.type = "highpass"; hp.frequency.value = 900;
      const t = ctx.currentTime;
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.22, t + 0.3);
      g.gain.setValueAtTime(0.22, t + seconds - 0.8);
      g.gain.exponentialRampToValueAtTime(0.0001, t + seconds);
      src.connect(hp).connect(g).connect(out);
      src.start(t);
    },
  };
})();
