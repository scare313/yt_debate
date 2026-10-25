// Ask the Gita show screen: plays a voiced answer (JSON + full.wav) in a calm 9:16 layout.
// The centre shows ONE thing at a time: hook -> verse card -> meaning -> purport -> practice -> reflection.
//
// URL options:  ?answer=<id>  which answer (default: newest)
//               ?clean        hide the preview controls (for recording)
//               ?autoplay     start by itself (OBS)
//               ?music=santoor (default) | kirtan | bansuri | harmonium | santoor | ambient | drone | file | none
//               ?credits      show the attribution line at the bottom (hidden by default)
//               ?safe         show the Shorts UI safe zone
//               ?live         live stream: plays answers back to back; NEW answers (from scripture/live.py)
//                             air next; when none are waiting it invites questions, then replays older ones
// Optional fixed background for every video: scripture/stage/assets/background.(jpg|png|webp)

const W = 1080, H = 1920;
const params = new URLSearchParams(location.search);
const $ = (id) => document.getElementById(id);
const SPEECH_WORDS = 7;                  // words per caption chunk for opening / explanation
const TEASERS = [
  "The Bhagavad-gītā has an answer…",
  "What the Gītā says might surprise you…",
  "An answer from the Bhagavad-gītā…",
  "The Gītā speaks to exactly this…",
];
// turn kind -> progress step, and which centre pane shows it
const STEP = { question: "question", opening: "question", verse: "verse", explanation: "meaning", quote: "meaning",
               practice: "practice", reflection: "reflect", cta: "reflect" };
const PANE = { question: "hook", opening: "speech", verse: "verse", explanation: "speech", quote: "quote",
               practice: "action", reflection: "reflect", cta: "speech" };
const STEPS = ["question", "verse", "meaning", "practice", "reflect"];

let rec = null, turns = [], audio = null, ctx = null, cur = -1, curWord = -1, ended = false;
const LIVE = params.has("live");
const known = new Set();            // live: answers that existed when the stream started (or already aired)
let rotation = 0, idleTimer = null;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (params.has("clean")) document.body.classList.add("clean");
if (params.has("safe")) document.body.classList.add("show-safe");
if (params.has("credits")) document.body.classList.add("credits");
if (LIVE) {
  document.body.classList.add("live");
  document.querySelector(".end-line.big").textContent = "🙏 Ask your question in the live chat";
}

function fit() {
  const c = document.body.classList.contains("clean") ? 0 : $("controls").offsetHeight;
  const s = Math.min(innerWidth / W, (innerHeight - c) / H);
  $("viewport").style.width = `${W * s}px`;
  $("viewport").style.height = `${H * s}px`;
  $("frame").style.transform = `scale(${s})`;
}
addEventListener("resize", fit);

const enc = (p) => p.split("/").map(encodeURIComponent).join("/");
const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const getJSON = async (u) => { const r = await fetch(u); if (!r.ok) throw new Error(`${u}: ${r.status}`); return r.json(); };

function message(msg, button = true) {
  $("start-msg").textContent = msg;
  $("start-btn").style.display = button ? "" : "none";
  $("start").classList.remove("hidden");
}

function loadBackground(exts = ["jpg", "png", "webp", "jpeg"]) {
  if (!exts.length) return;
  const img = new Image();
  img.onload = () => {
    $("bg").style.backgroundImage = `url("${img.src}")`;
    $("bg").classList.add("on");
    document.body.classList.add("has-bg");
  };
  img.onerror = () => loadBackground(exts.slice(1));
  img.src = `/scripture/stage/assets/background.${exts[0]}`;
}

// ---------- decoration: mandala, drifting light, and petals at the end ----------

function drawMandala() {
  const g = $("mandala");
  let svg = "";
  for (let ring = 1; ring <= 5; ring++) {
    const r = ring * 18, petals = 8 * ring;
    svg += `<circle r="${r}"/>`;
    for (let p = 0; p < petals; p++) {
      const a = (p / petals) * Math.PI * 2, x = Math.cos(a) * r, y = Math.sin(a) * r;
      svg += `<ellipse cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" rx="${(5 + ring).toFixed(1)}" ry="2.2" transform="rotate(${(a * 180 / Math.PI).toFixed(1)} ${x.toFixed(2)} ${y.toFixed(2)})"/>`;
    }
  }
  g.innerHTML = svg;
}

const motes = Array.from({ length: 60 }, (_, i) => ({ x: (i * 157) % W, y: (i * 389) % H, r: 1.5 + (i % 4), s: 0.15 + (i % 5) * 0.07 }));
const PETAL_COLORS = ["#f6a04d", "#f7c76b", "#ef7f6a", "#fde3a7", "#f39bb3"];
const petals = Array.from({ length: 46 }, (_, i) => ({
  x: (i * 211) % W, y: -60 - ((i * 97) % 900), s: 1.6 + (i % 5) * 0.45, sway: 0.6 + (i % 3) * 0.4,
  rot: i * 0.7, spin: 0.01 + (i % 4) * 0.006, size: 14 + (i % 4) * 5, color: PETAL_COLORS[i % PETAL_COLORS.length],
}));

function drawParticles(time) {
  const c = $("particles").getContext("2d");
  c.clearRect(0, 0, W, H);
  for (const m of motes) {
    m.y -= m.s; if (m.y < -10) m.y = H + 10;
    const grd = c.createRadialGradient(m.x, m.y, 0, m.x, m.y, m.r * 4);
    grd.addColorStop(0, "rgba(255,214,140,.5)"); grd.addColorStop(1, "rgba(255,214,140,0)");
    c.fillStyle = grd; c.beginPath(); c.arc(m.x, m.y, m.r * 4, 0, Math.PI * 2); c.fill();
  }
  const pc = $("petals").getContext("2d");
  pc.clearRect(0, 0, W, H);
  if (!ended) return;
  for (const p of petals) {                       // gentle flower shower over the end card
    p.y += p.s; p.rot += p.spin; if (p.y > H + 40) { p.y = -40; }
    const x = p.x + Math.sin(time / 900 + p.rot) * 30 * p.sway;
    pc.save(); pc.translate(x, p.y); pc.rotate(p.rot);
    pc.fillStyle = p.color; pc.globalAlpha = 0.85;
    pc.beginPath(); pc.ellipse(0, 0, p.size, p.size * 0.55, 0, 0, Math.PI * 2); pc.fill();
    pc.restore();
  }
}

// ---------- background music (synthesized in the browser: no sound files, no copyright) ----------
// ?music=santoor (default) | kirtan | bansuri | harmonium | ambient | drone | file | none
//   file = scripture/stage/assets/music.(mp3|ogg|m4a|wav), looped.  Every style ducks under the narrator.

const MUSIC_STYLES = ["kirtan", "bansuri", "harmonium", "santoor", "ambient", "drone", "file", "none"];

const Music = (() => {
  const mode = params.has("nodrone") ? "none" : (params.get("music") || "santoor");
  let started = false, bus = null, verb = null;
  const C3 = 130.81, C4 = 261.63;
  const jitter = () => (Math.random() - 0.5) * 0.016;

  // ---- building blocks ----
  function noise(seconds) {
    const b = ctx.createBuffer(1, Math.floor(ctx.sampleRate * seconds), ctx.sampleRate);
    const d = b.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    const src = ctx.createBufferSource(); src.buffer = b; return src;
  }
  function env(g, t, peak, a, r) {
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(peak, t + a);
    g.gain.exponentialRampToValueAtTime(0.0001, t + a + r);
  }
  function reverb(seconds = 3.2) {               // soft hall: decaying stereo noise impulse
    const len = Math.floor(ctx.sampleRate * seconds), ir = ctx.createBuffer(2, len, ctx.sampleRate);
    for (let ch = 0; ch < 2; ch++) {
      const d = ir.getChannelData(ch);
      for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 2.6);
    }
    const c = ctx.createConvolver(); c.buffer = ir;
    const g = ctx.createGain(); g.gain.value = 0.35;
    c.connect(g).connect(bus);
    return c;
  }
  const out = (node, wet = 0.5) => {            // dry to the bus, some to the hall
    node.connect(bus);
    const s = ctx.createGain(); s.gain.value = wet; node.connect(s).connect(verb);
  };

  // ---- instruments ----
  function tanpura(t, k, level = 0.035) {
    const f = [196.0, 261.63, 261.63, 130.81][k % 4];
    const o = ctx.createOscillator(), lp = ctx.createBiquadFilter(), g = ctx.createGain();
    o.type = "sawtooth"; o.frequency.value = f; o.detune.value = (Math.random() - .5) * 8;
    lp.type = "lowpass"; lp.frequency.setValueAtTime(2000, t); lp.frequency.exponentialRampToValueAtTime(450, t + 3);
    env(g, t, level, 0.03, 4.4);
    o.connect(lp).connect(g); out(g, 0.3); o.start(t); o.stop(t + 4.6);
  }
  function thom(t, v = 1) {
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = "sine"; o.frequency.setValueAtTime(115, t); o.frequency.exponentialRampToValueAtTime(52, t + 0.32);
    env(g, t, 0.55 * v, 0.006, 0.42); o.connect(g); out(g, 0.15); o.start(t); o.stop(t + 0.5);
  }
  function na(t, v = 1) {
    const o = ctx.createOscillator(), o2 = ctx.createOscillator(), g = ctx.createGain();
    o.type = "sine"; o.frequency.value = 466; o2.type = "sine"; o2.frequency.value = 932 * 1.01;
    env(g, t, 0.16 * v, 0.003, 0.2); o.connect(g); o2.connect(g); out(g, 0.25);
    o.start(t); o2.start(t); o.stop(t + 0.3); o2.stop(t + 0.3);
    const n = noise(0.05), bp = ctx.createBiquadFilter(), ng = ctx.createGain();
    bp.type = "bandpass"; bp.frequency.value = 2500; bp.Q.value = 1.5; env(ng, t, 0.12 * v, 0.001, 0.04);
    n.connect(bp).connect(ng); out(ng, 0.2); n.start(t);
  }
  function ta(t, v = 1) {
    const n = noise(0.08), bp = ctx.createBiquadFilter(), g = ctx.createGain();
    bp.type = "bandpass"; bp.frequency.value = 1100; bp.Q.value = 0.9; env(g, t, 0.18 * v, 0.002, 0.06);
    n.connect(bp).connect(g); out(g, 0.2); n.start(t);
  }
  function kartal(t, open) {
    const decay = open ? 0.9 : 0.12, g = ctx.createGain();
    env(g, t, open ? 0.07 : 0.055, 0.002, decay); out(g, 0.4);
    for (const f of [2093, 3170, 4699, 6020]) {
      const o = ctx.createOscillator(); o.type = "sine"; o.frequency.value = f * (1 + (Math.random() - .5) * 0.004);
      o.connect(g); o.start(t); o.stop(t + decay + 0.05);
    }
  }
  // Bansuri: breathy sine with vibrato, gliding (meend) from the previous note
  let lastFlute = null;
  function flute(t, f, dur) {
    const o = ctx.createOscillator(), o2 = ctx.createOscillator(), g = ctx.createGain(), h = ctx.createGain();
    const from = lastFlute || f; lastFlute = f;
    o.type = "sine"; o.frequency.setValueAtTime(from, t); o.frequency.exponentialRampToValueAtTime(f, t + 0.14);
    o2.type = "sine"; o2.frequency.setValueAtTime(from * 2, t); o2.frequency.exponentialRampToValueAtTime(f * 2, t + 0.14);
    const lfo = ctx.createOscillator(), depth = ctx.createGain();
    lfo.frequency.value = 5.2; depth.gain.setValueAtTime(0, t); depth.gain.linearRampToValueAtTime(f * 0.012, t + 0.5);
    lfo.connect(depth); depth.connect(o.frequency); depth.connect(o2.frequency);
    h.gain.value = 0.12; o2.connect(h).connect(g); o.connect(g);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.09, t + 0.12);
    g.gain.setValueAtTime(0.09, t + Math.max(0.15, dur - 0.25)); g.gain.exponentialRampToValueAtTime(0.0001, t + dur + 0.15);
    const n = noise(dur + 0.2), bp = ctx.createBiquadFilter(), ng = ctx.createGain();
    bp.type = "bandpass"; bp.frequency.value = f * 2; bp.Q.value = 6;
    ng.gain.setValueAtTime(0.0001, t); ng.gain.exponentialRampToValueAtTime(0.025, t + 0.1); ng.gain.exponentialRampToValueAtTime(0.0001, t + dur + 0.15);
    n.connect(bp).connect(ng).connect(g);
    out(g, 0.7);
    for (const x of [o, o2, lfo]) { x.start(t); x.stop(t + dur + 0.25); }
    n.start(t);
  }
  // Harmonium: two detuned reeds per note, bellows breathing
  function reed(t, f, dur, level) {
    const g = ctx.createGain(), lp = ctx.createBiquadFilter();
    lp.type = "lowpass"; lp.frequency.value = 1300;
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(level, t + 1.2);
    g.gain.setValueAtTime(level, t + dur - 1.2); g.gain.exponentialRampToValueAtTime(0.0001, t + dur + 0.4);
    for (const [type, det] of [["sawtooth", -6], ["sawtooth", 6], ["square", 0]]) {
      const o = ctx.createOscillator(); o.type = type; o.frequency.value = f; o.detune.value = det;
      o.connect(lp); o.start(t); o.stop(t + dur + 0.5);
    }
    lp.connect(g); out(g, 0.5);
  }
  function bell(t, f = 523.25, level = 0.05) {
    for (const [ratio, decay, v] of [[1, 4, 1], [2.0, 2.5, .5], [2.76, 2, .4], [5.4, 1.2, .25]]) {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = "sine"; o.frequency.value = f * ratio; env(g, t, level * v, 0.004, decay);
      o.connect(g); out(g, 0.8); o.start(t); o.stop(t + decay + 0.1);
    }
  }
  // Santoor: hammered strings, quick attack, long shimmering decay
  function pluck(t, f, v = 1) {
    const g = ctx.createGain();
    env(g, t, 0.06 * v, 0.003, 1.6);
    for (const [type, ratio, det] of [["triangle", 1, 0], ["sine", 2, 4], ["sine", 1, -5]]) {
      const o = ctx.createOscillator(); o.type = type; o.frequency.value = f * ratio; o.detune.value = det;
      o.connect(g); o.start(t); o.stop(t + 1.7);
    }
    out(g, 0.6);
  }
  // Ambient pad: detuned saws through a slowly moving filter
  function pad(t, notes, dur) {
    const g = ctx.createGain(), lp = ctx.createBiquadFilter(), lfo = ctx.createOscillator(), lg = ctx.createGain();
    lp.type = "lowpass"; lp.frequency.value = 700; lfo.frequency.value = 0.07; lg.gain.value = 300;
    lfo.connect(lg).connect(lp.frequency); lfo.start(t); lfo.stop(t + dur + 2);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.03, t + 2.5);
    g.gain.setValueAtTime(0.03, t + dur - 1); g.gain.exponentialRampToValueAtTime(0.0001, t + dur + 2);
    for (const f of notes) for (const det of [-8, 0, 8]) {
      const o = ctx.createOscillator(); o.type = "sawtooth"; o.frequency.value = f; o.detune.value = det;
      o.connect(lp); o.start(t); o.stop(t + dur + 2.2);
    }
    lp.connect(g); out(g, 0.6);
  }

  // ---- styles: each schedules its own events a little ahead of time ----
  const BHUPALI = [261.63, 293.66, 329.63, 392.0, 440.0, 523.25, 587.33, 659.25];   // S R G P D S' R' G'
  const PHRASES = [
    [[3, 2], [4, 1], [5, 3], [4, 1], [3, 1], [2, 4]],
    [[2, 1], [3, 1], [4, 2], [3, 1], [2, 1], [1, 2], [0, 4]],
    [[0, 1], [1, 1], [2, 2], [3, 2], [4, 1], [3, 1], [2, 4]],
    [[4, 2], [5, 2], [6, 1], [5, 1], [4, 2], [3, 4]],
  ];
  const SANTOOR = [0, 2, 3, 5, 4, 3, 2, 3, 0, 2, 4, 5, 7, 5, 4, 2];

  const styles = {
    kirtan(state, ahead) {
      const EIGHTH = 60 / 76 / 2;
      while (state.nextPluck < ahead) { tanpura(state.nextPluck, state.k++); state.nextPluck += 1.15; }
      const M = ["thom", "", "na", "ta", "thom", "thom", "na", ""], K = ["ching", "", "ching", "", "chong", "", "", ""];
      while (state.nextBar < ahead) {
        for (let e = 0; e < 8; e++) {
          const t = state.nextBar + e * EIGHTH + jitter(), v = 0.8 + Math.random() * 0.25;
          const m = (state.bar % 4 === 3 && e === 7) ? "na" : M[e];
          if (m === "thom") thom(t, v); else if (m === "na") na(t, v); else if (m === "ta") ta(t, v);
          if (K[e]) kartal(t, K[e] === "chong");
        }
        state.bar++; state.nextBar += 8 * EIGHTH;
      }
    },
    bansuri(state, ahead) {
      while (state.nextPluck < ahead) { tanpura(state.nextPluck, state.k++, 0.028); state.nextPluck += 1.4; }
      const BEAT = 1.0;
      while (state.nextBar < ahead) {
        const phrase = PHRASES[state.bar % PHRASES.length];
        let t = state.nextBar;
        for (const [n, beats] of phrase) { flute(t, BHUPALI[n], beats * BEAT * 0.95); t += beats * BEAT; }
        state.bar++; state.nextBar = t + 2.5 * BEAT;          // breathe between phrases
      }
    },
    harmonium(state, ahead) {
      while (state.nextBar < ahead) {
        const dur = 9;
        for (const f of [C3, 196.0, C4]) reed(state.nextBar, f, dur, 0.022);
        if (state.bar % 2 === 0) bell(state.nextBar + 1.5);
        state.bar++; state.nextBar += dur - 1.5;              // overlap for a seamless drone
      }
    },
    santoor(state, ahead) {
      while (state.nextPluck < ahead) { tanpura(state.nextPluck, state.k++, 0.025); state.nextPluck += 1.4; }
      const STEP = 60 / 72 / 2;
      while (state.nextBar < ahead) {
        const shift = [0, 0, 1, -1][state.bar % 4];
        SANTOOR.forEach((n, i) => {
          const idx = Math.max(0, Math.min(BHUPALI.length - 1, n + shift));
          pluck(state.nextBar + i * STEP + jitter(), BHUPALI[idx], i % 4 === 0 ? 1 : 0.7);
        });
        state.bar++; state.nextBar += SANTOOR.length * STEP + STEP * 4;
      }
    },
    ambient(state, ahead) {
      while (state.nextPluck < ahead) { tanpura(state.nextPluck, state.k++, 0.02); state.nextPluck += 1.6; }
      const CHORDS = [[C3, 196.0, C4], [110.0, 164.81, 220.0], [C3, 196.0, 329.63], [146.83, 220.0, 293.66]];
      while (state.nextBar < ahead) { pad(state.nextBar, CHORDS[state.bar++ % CHORDS.length], 10); state.nextBar += 8.5; }
    },
    drone(state, ahead) {
      while (state.nextPluck < ahead) { tanpura(state.nextPluck, state.k++); state.nextPluck += 1.15; }
    },
  };

  function playFile(exts = ["mp3", "ogg", "m4a", "wav"]) {
    if (!exts.length) return;
    const el = new Audio(`/scripture/stage/assets/music.${exts[0]}`);
    el.loop = true; el.crossOrigin = "anonymous";
    el.addEventListener("error", () => playFile(exts.slice(1)), { once: true });
    el.addEventListener("canplay", () => { ctx.createMediaElementSource(el).connect(bus); el.play(); }, { once: true });
  }

  return {
    mode,
    start() {
      if (started || mode === "none" || !ctx) return;
      started = true;
      bus = ctx.createGain(); bus.gain.value = 0.9; bus.connect(ctx.destination);
      verb = reverb();
      if (mode === "file") return playFile();
      const play = styles[mode] || styles.kirtan;
      const state = { nextPluck: ctx.currentTime + 0.1, k: 0, nextBar: ctx.currentTime + 0.3, bar: 0 };
      if (mode === "kirtan" || mode === "drone") {
        const hum = ctx.createOscillator(), hg = ctx.createGain();
        hum.type = "sine"; hum.frequency.value = 65.4; hg.gain.value = 0.02; hum.connect(hg).connect(bus); hum.start();
      }
      setInterval(() => play(state, ctx.currentTime + 2), 250);
    },
    duck(speaking) {                       // quieter under the narrator, fuller in the pauses and on the end card
      if (!bus) return;
      bus.gain.setTargetAtTime(speaking ? (mode === "file" ? 0.18 : 0.28) : 0.9, ctx.currentTime, 0.25);
    },
  };
})();

// ---------- load ----------

async function init() {
  fit(); drawMandala(); loadBackground();
  try {
    const list = await getJSON("/api/answers");
    for (const a of list) {
      const o = document.createElement("option");
      o.value = a.id;
      o.textContent = `${a.question}  ·  ${a.verses.join(", ")}  ·  ${a.seconds}s`;
      $("pick").append(o);
    }
    if (LIVE) {
      list.forEach((a) => known.add(a.id));
      showIdle();
      if (params.has("autoplay")) setTimeout(() => liveNext(), 800);
      else message("Live mode: click to start the stream loop");
      return;
    }
    const id = params.get("answer") || list[0]?.id;
    if (!id) return message("No voiced answers yet. Run scripture/ask.py \"question\" --voice", false);
    $("pick").value = id;
    await load(id);
  } catch (e) { message(`Could not load: ${e.message}. Is tools/stage_server.py running?`, false); }
}

async function load(id) {
  if (audio) { audio.pause(); audio = null; }
  ended = false;
  rec = await getJSON(`/scripture/data/answers/${enc(id)}.json`);
  turns = rec.turns.filter((t) => t.start_s !== undefined);
  $("show").textContent = $("end-show").textContent = rec.show || "Ask the Gita";
  const who = rec.asker ? `🙏 ${rec.asker} asks` : "🙏 Today's question";
  $("q-who").textContent = $("hook-who").textContent = who;
  $("q-text").textContent = $("hook-q").textContent = rec.question;
  const h = [...rec.question].reduce((a, c) => (a * 31 + c.codePointAt(0)) >>> 0, 7);
  $("hook-tease").textContent = TEASERS[h % TEASERS.length];
  $("attribution").textContent = `${rec.attribution || ""} ${rec.disclaimer || ""}`.trim();
  for (const t of turns) {
    const words = t.text.split(/\s+/).filter(Boolean);
    const weights = words.map((w) => [...w].length + 1);
    const total = weights.reduce((a, b) => a + b, 0) || 1;
    let acc = 0;
    t._words = words.map((w, i) => { const s = t.start_s + (acc / total) * t.audio_seconds; acc += weights[i]; return { w, s }; });
  }
  const blob = await (await fetch(`/scripture/data/answers/${enc(rec.audio_full)}`)).blob();
  audio = new Audio(URL.createObjectURL(blob));
  audio.addEventListener("ended", () => {
    ended = true; document.body.classList.add("ended"); $("play").textContent = "▶"; $("endcard").classList.add("on");
    document.title = "DONE";
    if (LIVE) setTimeout(() => liveNext(), 6000);   // end card for a few seconds, then the next answer
  });
  audio.addEventListener("play", () => { ended = false; document.body.classList.remove("ended"); $("endcard").classList.remove("on"); });
  cur = curWord = -1;
  cur = 0; onTurn(0);                       // the first frame already shows the hook (matters for recording)
  if (LIVE) return;                         // the live loop starts playback itself
  if (params.has("autoplay")) setTimeout(() => play().catch(() => message(rec.question)), 800);
  else message(rec.question);
}

async function play() {
  if (!audio) return;
  if (!ctx) {
    ctx = new AudioContext();
    ctx.createMediaElementSource(audio).connect(ctx.destination);
  }
  await ctx.resume();
  Music.start();
  $("start").classList.add("hidden");
  await audio.play();
  $("play").textContent = "⏸";
}

$("start-btn").onclick = () => (LIVE && !audio ? liveNext() : play());
// Music picker (preview only): switching reloads with ?music=<style>, keeping the current answer.
for (const m of MUSIC_STYLES) {
  const o = document.createElement("option"); o.value = m; o.textContent = `🎵 ${m}`; $("music").append(o);
}
$("music").value = Music.mode;
$("music").onchange = (e) => { const u = new URL(location); u.searchParams.set("music", e.target.value); location.href = u; };
$("play").onclick = () => (audio && !audio.paused ? (audio.pause(), ($("play").textContent = "▶")) : play());
$("restart").onclick = () => { if (audio) { audio.currentTime = 0; play(); } };
$("pick").onchange = async (e) => {
  const u = new URL(location); u.searchParams.set("answer", e.target.value); history.replaceState(null, "", u);
  await load(e.target.value);
};

// ---------- live loop ----------

function showIdle() {
  $("hook-who").textContent = "🔴 LIVE · " + ($("show").textContent || "Ask the Gita");
  $("hook-q").textContent = "Ask your question in the live chat";
  $("hook-tease").textContent = "Answers from the Bhagavad-gītā, live…";
  for (const el of document.querySelectorAll(".pane")) el.classList.toggle("on", el.id === "hook");
  document.querySelectorAll("#steps span").forEach((el) => el.classList.remove("done", "now"));
  $("question").classList.add("hidden");
  $("progress").style.width = "0";
  $("endcard").classList.remove("on");
  document.body.classList.remove("ended");
}

async function liveNext() {
  clearTimeout(idleTimer);
  if (!ctx) { ctx = new AudioContext(); await ctx.resume(); Music.start(); }   // first click / OBS autoplay
  $("start").classList.add("hidden");
  let list = [];
  try { list = await getJSON("/api/answers"); } catch { /* server hiccup: retry below */ }
  const fresh = list.filter((a) => !known.has(a.id)).reverse();        // oldest new question first
  let id = fresh[0]?.id;
  if (!id) {                                                            // nothing new: invite questions, then replay
    showIdle();
    for (let s = 0; s < 14; s++) {                                      // ~14 s, but a new answer interrupts at once
      await sleep(1000);
      try { list = await getJSON("/api/answers"); } catch { continue; }
      if (list.some((a) => !known.has(a.id))) return liveNext();
    }
    if (!list.length) return liveNext();
    id = list[rotation++ % list.length].id;
  }
  known.add(id);
  await load(id);
  await audio.play();
  $("play").textContent = "⏸";
}

// ---------- timeline ----------

function turnAt(t) {
  let i = 0;
  while (i + 1 < turns.length && turns[i + 1].start_s <= t + 0.05) i++;
  return i;
}

const verseRef = (vid) => `Bhagavad-gītā ${(vid || "").replace(/^BG /, "")}`;

function onTurn(i) {
  const t = turns[i], kind = t.kind;
  const pane = PANE[kind] || "speech";

  // progress steps
  const step = STEPS.indexOf(STEP[kind] || "question");
  document.querySelectorAll("#steps span").forEach((el, k) => {
    el.classList.toggle("done", k < step);
    el.classList.toggle("now", k === step);
  });

  // exactly one centre pane
  const panes = { hook: $("hook"), verse: $("verse-card").parentElement, speech: $("speech"),
                  quote: $("quote-card").parentElement, action: $("action-card").parentElement, reflect: $("reflect") };
  for (const [name, el] of Object.entries(panes)) el.classList.toggle("on", name === pane);
  $("question").classList.toggle("hidden", ["hook", "reflect", "verse", "quote"].includes(pane));

  // the latest verse (also correct after seeking)
  const lastVerse = turns.slice(0, i + 1).reverse().find((x) => x.kind === "verse");
  const vid = lastVerse?.verse, v = vid && rec.verse_texts?.[vid];
  if (v && $("verse-card").dataset.vid !== vid) {
    $("verse-card").dataset.vid = vid;
    $("v-ref").textContent = verseRef(vid);
    $("v-deva").innerHTML = esc(v.devanagari).replace(/\n/g, "<br>");
    $("v-translit").innerHTML = esc(v.transliteration).replace(/\n/g, "<br>");
  }
  $("speech-pill").textContent = kind === "explanation" && vid ? `What it means · ${verseRef(vid).replace("Bhagavad-gītā", "BG")}` : "";
  if (kind === "quote") $("quote-ref").textContent = `— Purport to ${verseRef(t.verse || vid)}`;
  $("action-card").classList.remove("ticked");
  curWord = -1;
}

// Which words a pane shows, and where.
function wordsFor(t) {
  if (t.kind === "verse") {                              // only the book's translation, not "The Bhagavad-gita ... says:"
    const k = t._words.findIndex((x) => /says:$/.test(x.w));
    return { el: $("v-trans"), words: t._words.slice(k + 1), all: true };
  }
  if (t.kind === "quote") {
    const k = t._words.findIndex((x) => /purport:$/.test(x.w));
    return { el: $("quote-text"), words: t._words.slice(k + 1), all: true };
  }
  if (t.kind === "practice") return { el: $("action-text"), words: t._words, all: true };
  if (t.kind === "reflection") return { el: $("reflect-text"), words: t._words, all: true };
  if (t.kind === "question") return null;               // already big on the hook
  return { el: $("speech-text"), words: t._words, all: false };
}

function renderWords(t, time) {
  const spec = wordsFor(t);
  if (!spec) return;
  const { el, words, all } = spec;
  let w = -1;
  while (w + 1 < words.length && words[w + 1].s <= time) w++;
  if (w === curWord && el.dataset.turn === String(cur)) return;
  curWord = w;
  el.dataset.turn = String(cur);
  let from = 0, to = words.length;
  if (!all) {                                            // captions: one chunk at a time
    from = Math.floor(Math.max(w, 0) / SPEECH_WORDS) * SPEECH_WORDS;
    to = from + SPEECH_WORDS;
    if (el.dataset.chunk !== `${cur}:${from}`) {
      el.dataset.chunk = `${cur}:${from}`;
      el.classList.remove("fade"); void el.offsetWidth; el.classList.add("fade");
    }
  }
  el.innerHTML = words.slice(from, to).map((x, k) => {
    const idx = from + k;
    return `<span class="kw ${idx === w ? "now" : idx > w ? "future" : ""}">${esc(x.w)}</span>`;
  }).join(" ");
  if (t.kind === "practice" && w >= words.length - 1) $("action-card").classList.add("ticked");
}

function loop(now) {
  drawParticles(now || 0);
  if (audio && turns.length) {
    const t = audio.currentTime;
    const i = turnAt(t);
    if (i !== cur) { cur = i; onTurn(i); }
    renderWords(turns[i], t);
    const tt = turns[i];
    Music.duck(!audio.paused && t >= tt.start_s && t <= tt.start_s + tt.audio_seconds);
    const d = audio.duration || 0;
    $("progress").style.width = d ? `${Math.min(100, (t / d) * 100)}%` : "0";
    const s = Math.floor(t), dd = Math.round(d);
    $("time").textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")} / ${Math.floor(dd / 60)}:${String(dd % 60).padStart(2, "0")}`;
  }
  requestAnimationFrame(loop);
}

init();
requestAnimationFrame(loop);
