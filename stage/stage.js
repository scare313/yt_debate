// Dangal 24x7 show screen: plays a saved debate (JSON + full.wav) in the 9:16 news layout.
//
// URL options:  ?debate=<id>   which debate (default: newest)
//               ?clean         hide the preview controls (for recording)
//               ?safe          show the Shorts UI safe zone

const W = 1080, H = 1920;
const params = new URLSearchParams(location.search);
const $ = (id) => document.getElementById(id);

const COLORS = {
  bright_red: "#ff4b5c", red: "#e53935", bright_green: "#3ddc84", green: "#2e9d4f",
  bright_cyan: "#22d3ee", cyan: "#0891b2", bright_magenta: "#e879f9", magenta: "#c026d3",
  bright_yellow: "#facc15", yellow: "#ca8a04", bright_blue: "#60a5fa", blue: "#2563eb", white: "#e5e7eb",
};
const SIDE_LABEL = { FOR: "पक्ष में", AGAINST: "विपक्ष में" };
const WORDS_PER_CAPTION = 7;
const CTA_LINES = ["🎙️ स्टूडियो से लाइव", "💬 सवाल पूछिए कमेंट में — रितिका अगले शो में पढ़ेंगी!"];
// How much each kind of turn heats up the drama meter (0-100)
const DRAMA = { intro: 8, question: 3, answer: 5, cutin: 16, comment: 9, viewer: 7, closing: 5,
                opening: 6, rebuttal: 8 };
const AVATAR_COLORS = ["#2563eb", "#db2777", "#059669", "#7c3aed", "#ea580c", "#0891b2"];
const CHAT_ICON = { greeting: "👋", reaction: "", vote: "🗳️", question: "💬", topic: "💡", chatter: "💬" };
const MAX_RAIN = 70;
const hash = (str) => [...str].reduce((h, ch) => (h * 31 + ch.codePointAt(0)) >>> 0, 7);

let chars = {}, debate = null, turns = [], hostKey = null, castOrder = [];
let boxes = {};               // character key -> box element (anchor included)
let audio = null, ctx = null, analyser = null, waveData = null;
let curTurn = -1, curWord = -1;
let rainPlan = [], rainNext = 0, lastT = 0;   // scheduled emoji rain

// ---------- setup ----------

if (params.has("clean")) document.body.classList.add("clean");
if (params.has("safe")) document.body.classList.add("show-safe");

function fit() {
  const controls = document.body.classList.contains("clean") ? 0 : $("controls").offsetHeight;
  const s = Math.min(innerWidth / W, (innerHeight - controls) / H);
  $("viewport").style.width = `${W * s}px`;
  $("viewport").style.height = `${H * s}px`;
  $("frame").style.transform = `scale(${s})`;
}
addEventListener("resize", fit);

const enc = (path) => path.split("/").map(encodeURIComponent).join("/");
const getJSON = async (url) => {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
};

// Optional logo image (stage/assets/logo.png / .jpg / .webp) replaces the drawn DANGAL 24x7 badge.
function loadLogo(exts = ["png", "jpg", "jpeg", "webp"]) {
  if (!exts.length) return;
  const img = new Image();
  img.onload = () => { const logo = document.querySelector(".logo"); logo.innerHTML = ""; logo.classList.add("has-img"); logo.append(img); };
  img.onerror = () => loadLogo(exts.slice(1));
  img.src = `/stage/assets/logo.${exts[0]}`;
}

async function init() {
  fit();
  loadLogo();
  try {
    chars = await getJSON("/api/characters");
    const list = await getJSON("/api/debates");
    const pick = $("pick");
    for (const d of list) {
      const o = document.createElement("option");
      o.value = d.id;
      o.textContent = `${d.topic}  ·  ${d.speakers.join(" vs ")}  ·  ${Math.floor(d.seconds / 60)}:${String(d.seconds % 60).padStart(2, "0")}`;
      pick.append(o);
    }
    const id = params.get("debate") || list[0]?.id;
    if (!id) return startMessage("कोई आवाज़ वाली बहस नहीं मिली। पहले debate.py से एक बहस बनाइए। (No voiced debates found.)", false);
    pick.value = id;
    await load(id);
  } catch (e) {
    startMessage(`Could not load: ${e.message}. Is tools/stage_server.py running?`, false);
  }
}

function startMessage(msg, showButton = true) {
  $("start-msg").textContent = msg;
  $("start-btn").style.display = showButton ? "" : "none";
  $("start").classList.remove("hidden");
}

async function load(id) {
  if (audio) { audio.pause(); audio = null; }
  debate = await getJSON(`/data/debates/${enc(id)}.json`);
  turns = debate.turns.filter((t) => t.start_s !== undefined);
  castOrder = Object.keys(debate.sides);                       // judge-score order
  const debaters = [...castOrder].sort((a, b) => (debate.sides[a] === "FOR" ? -1 : 1));
  hostKey = turns.find((t) => !(t.speaker in debate.sides))?.speaker || "ritika";
  build(debaters);

  // Fetch the audio as a blob so seeking works without HTTP range support.
  const blob = await (await fetch(`/data/debates/${enc(debate.audio_full)}`)).blob();
  audio = new Audio(URL.createObjectURL(blob));
  audio.addEventListener("ended", () => ($("play").textContent = "▶"));
  ctx && connectAnalyser();
  curTurn = curWord = -1;
  render(0);
  startMessage(`${debate.topic}`);
}

function charInfo(key) {
  const c = chars[key] || {};
  const p = debate.panel?.[key] || {};
  return {
    name: c.name || p.name || key,
    title: c.title || p.title || "",
    color: COLORS[c.color] || c.color || "#3b4a8a",
    emoji: c.emoji || "🎙️",
  };
}

function portrait(el, key) {
  const info = charInfo(key);
  el.style.setProperty("--c", info.color);
  const initials = info.name.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  el.innerHTML = `<div class="ph"><div class="ph-emoji">${info.emoji}</div><div class="ph-initials">${initials}</div></div>`;
  // Real art, once it exists: stage/assets/characters/<key>.png (or .jpg / .jpeg / .webp)
  const exts = ["png", "jpg", "jpeg", "webp"];
  const tryNext = (n) => {
    if (n >= exts.length) return;
    const img = new Image();
    img.onload = () => el.append(img);
    img.onerror = () => tryNext(n + 1);
    img.src = `/stage/assets/characters/${key}.${exts[n]}`;
  };
  tryNext(0);
}

function build(debaters) {
  boxes = {};
  // Anchor
  const a = charInfo(hostKey);
  portrait($("anchor-portrait"), hostKey);
  $("anchor-name").textContent = a.name;
  $("anchor-title").textContent = a.title;
  boxes[hostKey] = $("anchor");

  // Panelists: FOR on the left, AGAINST on the right
  debaters.forEach((key, i) => {
    const box = $(i === 0 ? "boxA" : "boxB");
    box.className = "box";
    box.innerHTML = "";
    box.append($("box-tpl").content.cloneNode(true));
    const info = charInfo(key);
    portrait(box.querySelector(".portrait"), key);
    box.querySelector(".strip-name").textContent = info.name;
    box.querySelector(".strip-title").textContent = info.title;
    const side = box.querySelector(".side");
    side.textContent = SIDE_LABEL[debate.sides[key]] || debate.sides[key];
    side.classList.add(debate.sides[key] === "FOR" ? "for" : "against");
    box.style.setProperty("--c", info.color);
    boxes[key] = box;
  });

  $("topic").textContent = debate.topic;

  // Ticker: every chat message that passed moderation, plus running gags and calls to comment
  const chat = debate.chat || { messages: (debate.comments || []).map((c) => ({ ...c, kind: "question" })), votes: {} };
  const jokes = [hostKey, ...debaters].flatMap((k) => (chars[k]?.jokes || []).map((j) => `⚡ ${j}`));
  const chatItems = chat.messages.slice(-50).map((m) =>
    m.kind === "topic" ? `💡 ${m.name} का टॉपिक: ${m.text}` : `${CHAT_ICON[m.kind] ?? "💬"} ${m.name}: ${m.text}`.trim());
  const items = [
    "⚠️ यह एक AI व्यंग्य (सटायर) शो है — सभी किरदार काल्पनिक हैं",
    ...chatItems.slice(0, 12),
    ...jokes.slice(0, 2),
    "✍️ अपना सवाल कमेंट कीजिए — अगले एपिसोड में आपका नाम ऑन एयर!",
    ...chatItems.slice(12),
    ...jokes.slice(2),
    "📺 दंगल 24x7 — जहाँ बहस कभी ख़त्म नहीं होती",
  ];
  const once = items.map((t) => `<span>${escapeHTML(t)}</span>`).join("");
  $("ticker").innerHTML = once + once; // doubled for a seamless loop
  requestAnimationFrame(() => {        // constant reading speed however long the ticker is
    $("ticker").style.animationDuration = `${Math.max(30, $("ticker").scrollWidth / 2 / 140)}s`;
  });

  // Live poll from chat votes (or a call to vote when there are none yet)
  const [ka, kb] = debaters;
  const short = (k) => charInfo(k).name.split(/\s+/)[0];
  const va = chat.votes?.[ka] || 0, vb = chat.votes?.[kb] || 0;
  $("poll").classList.toggle("empty", va + vb === 0);
  $("poll-cta").textContent = `🗳️ कमेंट में लिखो: टीम ${short(ka)} या टीम ${short(kb)}!`;
  $("poll-a").textContent = short(ka);
  $("poll-b").textContent = short(kb);
  $("poll-a").style.color = charInfo(ka).color;
  $("poll-b").style.color = charInfo(kb).color;
  $("poll-bar").style.setProperty("--ca", "#15803d");
  $("poll-bar").style.setProperty("--cb", "#b91c1c");
  const pa = va + vb ? Math.round((100 * va) / (va + vb)) : 50;
  $("poll-fill").style.width = `${pa}%`;
  $("poll-pa").textContent = `${pa}%`;
  $("poll-pb").textContent = `${100 - pa}%`;

  // Emoji rain: every emoji from the chat, spread evenly (and deterministically) over the show
  const all = chat.messages.flatMap((m) => [...m.text].filter((ch) => /\p{Extended_Pictographic}/u.test(ch)).slice(0, 5));
  const span = turns.length ? turns[turns.length - 1].start_s : 0;
  const n = Math.min(all.length, MAX_RAIN);
  rainPlan = Array.from({ length: n }, (_, k) => {
    const h = hash(`${all[k]}${k}`);
    return { t: 3 + ((k + 0.5) / n) * Math.max(0, span - 3) + (h % 100) / 100, e: all[k], x: 90 + (h % 900), rot: (h % 60) - 30 };
  }).sort((a, b) => a.t - b.t);
  rainNext = 0;

  // Drama meter level after each turn; the verdict fills it up.
  let heat = 0;
  for (const t of turns) {
    const kind = t.kind || t.round || "";
    heat = kind === "verdict" ? 100 : Math.min(92, heat + (DRAMA[kind] ?? 5));
    t._drama = heat;
  }
  if (turns.length && !turns.some((t) => t.kind)) turns[turns.length - 1]._drama = 100; // older debates

  // Shoutouts for the verdict
  const names = [...new Set((debate.comments || []).map((c) => c.name))];
  $("shout-head").textContent = names.length ? "🙏 आज के सवाल पूछने वाले" : "🙋 अगले शो का पहला सवाल आपका हो सकता है!";
  $("shout-names").textContent = names.join(" · ");
  $("shout-names").style.display = names.length ? "" : "none";

  // Caption chunks with estimated word timings (proportional to word length)
  for (const t of turns) {
    // Stage directions like "(dramatic music)" are never spoken, so don't caption them.
    const words = t.text.replace(/[(\[][^)\]]*[)\]]/g, " ").split(/\s+/).filter(Boolean);
    const weights = words.map((w) => [...w].length + 1);
    const total = weights.reduce((x, y) => x + y, 0) || 1;
    let acc = 0;
    t._words = words.map((w, i) => {
      const start = t.start_s + (acc / total) * t.audio_seconds;
      acc += weights[i];
      return { w, start };
    });
  }
}

const escapeHTML = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ---------- playback ----------

function connectAnalyser() {
  const src = ctx.createMediaElementSource(audio);
  analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  waveData = new Uint8Array(analyser.fftSize);
  src.connect(analyser);
  analyser.connect(ctx.destination);
}

async function play() {
  if (!audio) return;
  if (!ctx) {
    ctx = new AudioContext();
    connectAnalyser();
  }
  await ctx.resume();
  $("start").classList.add("hidden");
  await audio.play();
  $("play").textContent = "⏸";
}

$("start-btn").onclick = play;
$("play").onclick = () => (audio && !audio.paused ? (audio.pause(), ($("play").textContent = "▶")) : play());
$("restart").onclick = () => { if (audio) { audio.currentTime = 0; play(); } };
$("pick").onchange = async (e) => {
  const url = new URL(location);
  url.searchParams.set("debate", e.target.value);
  history.replaceState(null, "", url);
  await load(e.target.value);
};

function turnAt(t) {
  let i = 0;
  while (i + 1 < turns.length && turns[i + 1].start_s <= t + 0.05) i++;
  return i;
}

function onTurn(i) {
  const turn = turns[i];
  const kind = turn.kind || turn.round || "";
  const isLast = i === turns.length - 1;

  for (const [key, el] of Object.entries(boxes)) {
    el.classList.toggle("active", key === turn.speaker);
    el.classList.toggle("asked-now", turn.speaker === hostKey && key === turn.to);
  }

  // Commenter spotlight: shown while the anchor reads the comment and while the panelist answers it
  const c = turn.comment;
  const prev = turns[i - 1]?.comment;
  $("comment").classList.toggle("on", !!c);
  if (c) {
    $("comment-text").textContent = c.text;
    $("comment-name").textContent = c.name;
    $("comment-avatar").textContent = [...c.name][0]?.toUpperCase() || "?";
    $("comment-avatar").style.setProperty("--av", AVATAR_COLORS[[...c.name].reduce((a, ch) => a + ch.charCodeAt(0), 0) % AVATAR_COLORS.length]);
  }

  // Welcome roll-call
  const rollcall = kind === "rollcall";
  $("welcome").classList.toggle("on", rollcall);
  if (rollcall) {
    const names = turn.names || [];
    $("welcome-names").innerHTML =
      names.map((nm, k) => `<span style="animation-delay:${0.15 * k}s">${escapeHTML(nm)}</span>`).join("") +
      (turn.more ? `<span class="more" style="animation-delay:${0.15 * names.length}s">+${turn.more} और</span>` : "");
  }

  // Verdict + shoutouts
  const verdictNow = kind === "verdict" || (isLast && turn.speaker === hostKey && !turn.kind);
  showVerdict(verdictNow);
  $("shout").classList.toggle("on", verdictNow);
  $("studio-tag").style.opacity = c || verdictNow || rollcall ? 0 : 1;

  // Drama meter + reaction stickers
  const before = turns[i - 1]?._drama ?? 0;
  $("meter-fill").style.width = `${turn._drama ?? 0}%`;
  if ((turn._drama ?? 0) - before >= 9) {
    $("meter").classList.remove("spike"); void $("meter").offsetWidth; $("meter").classList.add("spike");
  }
  if (kind === "cutin") sticker("🔥 बीच में कूदे!", boxes[turn.speaker], "hot");
  else if (c && !prev && turn.speaker === hostKey) sticker("📣 दर्शक का सवाल!", $("anchor"), "");
  else if (verdictNow) sticker("🎉 फ़ैसला आ गया!", $("frame").querySelector(".panels"), "party");
  else if (rollcall) sticker("👋 हाय चैट!", $("anchor"), "");
  else if (kind === "mood") {
    sticker("🔥 चैट में आग!", $("frame").querySelector(".panels"), "hot");
    $("poll").classList.remove("pulse"); void $("poll").offsetWidth; $("poll").classList.add("pulse");
    const top = Object.keys(turn.emojis || {});
    if (top.length) for (let k = 0; k < 18; k++) spawnEmoji(top[k % top.length], 90 + ((k * 137) % 900), k * 0.06, (k % 7) * 9 - 27);
  }

  const info = charInfo(turn.speaker);
  $("subs-speaker").textContent = info.name;
  $("subs-speaker").style.setProperty("--c", info.color);
  curWord = -1;
}

function spawnEmoji(e, x, delay = 0, rot = 15) {
  const el = document.createElement("span");
  el.textContent = e;
  el.style.left = `${x}px`;
  el.style.top = "1180px";            // rises from the panel boxes
  el.style.animationDelay = `${delay}s`;
  el.style.setProperty("--rot", `${rot}deg`);
  el.addEventListener("animationend", () => el.remove());
  $("rain").append(el);
}

function sticker(text, target, cls) {
  const el = $("sticker");
  if (!target) return;
  // Centre the sticker on the top part of the target, in frame (1080x1920) coordinates.
  const f = $("frame").getBoundingClientRect(), r = target.getBoundingClientRect();
  const scale = f.width / W;
  el.style.left = `${(r.left - f.left + r.width / 2) / scale}px`;
  el.style.top = `${(r.top - f.top) / scale + 90}px`;
  el.textContent = text;
  el.className = `sticker ${cls}`;
  void el.offsetWidth; // restart the animation
  el.classList.add("pop");
}

function showVerdict(on) {
  const v = debate.verdict || {};
  const parts = String(v.score || "").split("-");
  for (const key of castOrder) {
    const box = boxes[key];
    if (!box) continue;
    box.classList.toggle("winner", on && v.winner === key);
    box.classList.toggle("loser", on && v.winner && v.winner !== "draw" && v.winner !== key);
    box.classList.toggle("scored", on);
    // Older debates only have a "6-7" string whose order isn't reliable: winner gets the higher number.
    const nums = parts.map(Number).filter((n) => !isNaN(n)).sort((x, y) => y - x);
    const score = v.scores?.[key] ?? (v.winner === key ? nums[0] : nums[nums.length - 1]);
    box.querySelector(".score").textContent = v.scores ? `स्कोर ${Math.round(score)}/20` : `स्कोर ${score ?? "?"}`;
    if (on && v.winner === "draw") box.querySelector(".winner-banner").textContent = "🤝 बराबरी";
  }
}

function renderCaption(turn, t) {
  const words = turn._words;
  let w = 0;
  while (w + 1 < words.length && words[w + 1].start <= t) w++;
  if (w === curWord) return;
  curWord = w;
  const chunkStart = Math.floor(w / WORDS_PER_CAPTION) * WORDS_PER_CAPTION;
  const chunk = words.slice(chunkStart, chunkStart + WORDS_PER_CAPTION);
  $("subs-text").innerHTML = chunk
    .map((x, k) => {
      const idx = chunkStart + k;
      const cls = idx === w ? "now" : idx > w ? "future" : "";
      return `<span class="${cls}">${escapeHTML(x.w)}</span>`;
    })
    .join(" ");
}

function drawWave(canvas, color, live) {
  const g = canvas.getContext("2d");
  const { width, height } = canvas;
  g.clearRect(0, 0, width, height);
  const bars = 36, gap = 4, bw = (width - gap * (bars - 1)) / bars;
  g.fillStyle = live ? color : "rgba(255,255,255,.22)";
  for (let b = 0; b < bars; b++) {
    let amp = 0.04;
    if (live && waveData) {
      // Peak of this slice of the waveform, shaped so the middle bars run taller
      const n = waveData.length / bars;
      let peak = 0;
      for (let k = Math.floor(b * n); k < Math.floor((b + 1) * n); k++) peak = Math.max(peak, Math.abs(waveData[k] - 128));
      const shape = 0.55 + 0.45 * Math.sin((Math.PI * (b + 0.5)) / bars);
      amp = Math.max(0.06, Math.min(1, (peak / 70) * shape));
    }
    const h = Math.max(3, amp * height);
    g.fillRect(b * (bw + gap), (height - h) / 2, bw, h);
  }
}

function render(t) {
  if (!turns.length) return;
  const i = turnAt(t);
  if (i !== curTurn) {
    curTurn = i;
    onTurn(i);
  }
  const turn = turns[i];
  const speaking = t >= turn.start_s && t <= turn.start_s + turn.audio_seconds;
  renderCaption(turn, t);

  // The tag above Ritika's name alternates with a call to comment (driven by playback time,
  // so recordings come out the same every time).
  const cta = Math.floor(t / 6) % 2;
  if ($("studio-tag").dataset.cta !== String(cta)) {
    $("studio-tag").dataset.cta = cta;
    $("studio-tag").textContent = CTA_LINES[cta];
    $("studio-tag").classList.toggle("cta", cta === 1);
  }

  // Emoji rain: spawn what's due since the last frame (only while playing forward, not on seeks)
  if (t < lastT || t - lastT > 1) rainNext = rainPlan.findIndex((r) => r.t > t) === -1 ? rainPlan.length : rainPlan.findIndex((r) => r.t > t);
  else while (rainNext < rainPlan.length && rainPlan[rainNext].t <= t) {
    const r = rainPlan[rainNext++];
    spawnEmoji(r.e, r.x, 0, r.rot);
  }
  lastT = t;

  if (analyser && audio && !audio.paused) analyser.getByteTimeDomainData(waveData);
  for (const [key, el] of Object.entries(boxes)) {
    const canvas = el.querySelector("canvas.wave");
    if (canvas) drawWave(canvas, charInfo(key).color, speaking && key === turn.speaker && audio && !audio.paused);
  }
}

function loop() {
  if (audio) {
    const t = audio.currentTime;
    render(t);
    const m = Math.floor(t / 60), s = Math.floor(t % 60);
    const d = Math.round(audio.duration || 0);
    $("time").textContent = `${m}:${String(s).padStart(2, "0")} / ${Math.floor(d / 60)}:${String(d % 60).padStart(2, "0")}`;
  }
  requestAnimationFrame(loop);
}

init();
loop();
