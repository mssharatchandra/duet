import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const runtimeModules = process.env.RUNTIME_NODE_MODULES
  || "/Users/sharat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules";
const artifactToolUrl = pathToFileURL(path.join(runtimeModules, "@oai/artifact-tool/dist/artifact_tool.mjs")).href;
const { Presentation, PresentationFile } = await import(artifactToolUrl);
const OUT = path.join(ROOT, "docs/talk/Duet_Aira_Voice_AI_Tech_Talk_2026-08-25.pptx");
const RENDER_DIR = path.join(ROOT, ".local/final-deck-render");
const SOURCE_MD = path.join(ROOT, "docs/talk/FINAL_DECK_2026-08-25.md");
const BG = [
  path.join(ROOT, "docs/talk/assets/duet-bg-mountain.jpg"),
  path.join(ROOT, "docs/talk/assets/duet-bg-arch.jpg"),
  path.join(ROOT, "docs/talk/assets/duet-bg-beach.jpg"),
  path.join(ROOT, "docs/talk/assets/duet-bg-clouds.jpg"),
];

const C = {
  navy: "#102A43",
  cyan: "#288DC1",
  coral: "#D96C5F",
  teal: "#268C82",
  cream: "#FAF1DE",
  cream2: "#FFF8EA",
  pale: "#E8F3F6",
  line: "#8EBBD0",
  muted: "#4B687A",
  white: "#FFFFFF",
};

const W = 1280;
const H = 720;
const FONT = "Aptos";
const MONO = "Aptos Mono";

const specs = [
  { n: 1, title: "Humanising Voice AI", kind: "hero", body: ["Duet / Aira", "A month of building, breaking and measuring a real-time voice agent."], source: "Duet repository experiments, August 2026" },
  { n: 2, title: "A voice agent is a real-time control system", kind: "orbit", body: ["Listen", "decide", "speak", "yield", "remember", "act"], source: "Duet architecture" },
  { n: 3, title: "Demystifying the jargon", kind: "glossary", rows: [["VAD", "Voice Activity Detection", "Is someone speaking?"], ["ASR / STT", "Automatic Speech Recognition / Speech-to-Text", "What did they say?"], ["EOU", "End of Utterance / endpointing", "Are they finished?"], ["LLM TTFT", "Large-language-model time to first token", "When does thinking begin?"], ["TTS TTFB", "Text-to-speech time to first byte", "When can speech begin?"], ["Barge-in", "Interruption detection and recovery", "Can the caller take the floor?"], ["RTF", "Real-time factor", "Can inference keep up with speech?"]], source: "Duet learning guide" },
  { n: 4, title: "The waterfall tax", kind: "waterfall", body: ["speech end", "endpoint", "ASR", "reasoning", "TTS", "playback"], source: "Decision 0021 · docs/LATENCY_ARCHITECTURE.md" },
  { n: 5, title: "Fast models do not guarantee a fast conversation", kind: "owners", body: ["turn timing", "reasoning", "speech start", "playout"], source: "Duet latency architecture" },
  { n: 6, title: "Duet’s thesis: guarded speculative duplex", kind: "speculation", body: ["Start safe work early.", "Commit only when meaning is stable.", "Cancel everything stale."], source: "Duet architecture; concurrency is prior art" },
  { n: 7, title: "Concurrent lanes, causal gates", kind: "lanes", rows: [["LISTEN", "continuous audio"], ["TURN", "partial  →  stable  →  final"], ["POLICY", "consent · opt-out · barge-in · claims"], ["PLAN", "retrieval · reasoning"], ["ACT", "tool request"], ["SPEAK", "safe clause  →  audio"]], source: "Duet runtime lanes" },
  { n: 8, title: "What runs inside Aira", kind: "architecture", body: ["Browser", "Saaras", "Duet", "Gemini", "Bulbul", "Speaker"], source: "Duet Aira browser demo architecture" },
  { n: 9, title: "Live demo", kind: "demo", body: ["LIVE"], source: "Recorded Aira session" },
  { n: 10, title: "Speech quality is product quality", kind: "waveforms", body: ["If ASR misses the need, reasoning solves the wrong problem.", "If TTS rushes the answer, correct reasoning still feels wrong."], source: "Sarvam docs · Decisions 0009, 0017, 0020" },
  { n: 11, title: "The ASR eval changed the answer", kind: "bars", label: "WER at 5 dB noise ↓", data: [["base.en", 14.1], ["small.en", 8.7], ["MLX Whisper", 3.4], ["Parakeet", 2.7]], source: "eval/asr/README.md · 30 utterances × 7 conditions" },
  { n: 12, title: "TTS: optimize the clock people hear", kind: "timeline", label: "Time to first audio", data: [["Piper", 83], ["Sarvam warm", 223], ["Kokoro", 380]], source: "eval/tts/README.md · Decision 0022" },
  { n: 13, title: "Why Gemini won our reasoning gate", kind: "quadrant", body: ["grounded", "structured", "tool-capable", "fast enough"], source: "Gemini 3.1 Flash Lite docs · Decisions 0021–0022" },
  { n: 14, title: "Local reasoning: the speed–reliability wall", kind: "modeltable", rows: [["Qwen 0.8B", "153 ms", "fast, invented facts"], ["Qwen 4B", "1,623 ms", "relevant, too slow"], ["Gemma 1B", "760–1,750 ms", "schema / policy failures"], ["Gemma 4B", "2,858–3,142 ms", "grounded sample, slower than Gemini"], ["Gemini Flash Lite", "1,120 ms", "132/136 grounded-policy checks · chosen"]], source: "Local model measurements · Decisions 0021–0022" },
  { n: 15, title: "Moshi proved speed—and failed control", kind: "compare", rows: [["", "Handoff p50", "Takeover", "Overlap"], ["Moshi duplex", "240 ms", "0.24", "0.234"], ["Cascade", "1,880 ms", "0.00", "0.053"]], body: "In simple terms: it answered quickly, but often spoke at the wrong time.", source: "Moshi paper · eval/bench/RESULTS.md" },
  { n: 16, title: "Experiment 1: earlier speculation did not prove speed", kind: "nearbars", data: [["Before", 1943], ["Two-word speculation", 1912]], body: ["Start reasoning after two stable words, rather than wait for four.", "The reply should begin meaningfully sooner.", "31 ms difference across two live runs.", "Too small and too few runs: noise, not a proven speedup."], source: "GitHub PR #1 · Widen speculative-reasoning coverage" },
  { n: 17, title: "Experiment 2: the proxy win inverted", kind: "inversion", body: ["4.9× fewer free-run tokens", "+59% takeovers", "+41% overlap", "8× worse handoff"], caption: "In simple terms: we made the bot wait less; it interrupted people more often.", lesson: "EVAL RULE  ·  Eval the behaviour you care about—not the proxy that flatters your optimization.", source: "GitHub PR #2 · docs/DUPLEX_STEERING.md" },
  { n: 18, title: "Evals are the new PRDs", kind: "loop", body: ["scenario", "metric", "threshold", "regression test"], caption: "Why: live calls reveal failures a prompt cannot. We made each one a repeatable test.", source: "Duet CI and eval harnesses" },
  { n: 19, title: "The model does not own trust", kind: "guard", body: ["consent", "opt-out", "claims", "staleness", "capabilities"], caption: "Why: models can be wrong. They propose; deterministic code verifies consent, facts and permissions before speech or action.", source: "Duet policy and action adapters" },
  { n: 20, title: "If you cannot replay it, you cannot improve it", kind: "observability", body: [["01", "Langfuse", "Why: replay model + tool decisions."], ["02", "Prometheus + Grafana", "Why: spot latency + error regressions."], ["03", "Postgres", "Why: join turns, actions + outcomes."], ["04", "JSONL / Loki", "Why: diagnose event-level failures."]], caption: "Observability closes the loop: real failures become better eval cases before the next release.", subcaption: "Asynchronous telemetry—never on the audio path.", source: "Duet observability stack" },
  { n: 21, title: "Latest Aira run: a replayable live session", kind: "run", data: [["median response start", "443 ms"], ["interruptions", "3"], ["actions", "2"], ["user turns", "11"]], body: ["One trace connects responsiveness, interruptions, actions and the caller’s journey."], source: "Session 1787592808-61dd64 · trace 9722afa5…" },
  { n: 22, title: "Aira vs Sarvam Voice Agents: honest comparison", kind: "vendorbars", data: [["Aira local-plan", 443, "measured · one session"], ["Aira Gemini", 2260, "measured · rich response"], ["Sarvam", 500, "vendor claim · definition unpublished"]], source: "Duet traces · Sarvam Voice Agents product page" },
  { n: 23, title: "Why India is a voice market", kind: "numbers", data: [["22", "official languages"], ["2M+", "voice conversations/day¹"], ["₹3.50", "per minute¹"], ["$6.3M", "Bolna seed · 2026"]], caption: "The moat is not only a pretty voice: noisy telephony, dialects, interruption, cost, compliance, integrations and reliability at large volumes.", source: "¹Sarvam claims · Bolna funding announcement" },
  { n: 24, title: "ASBL inquiry reactivation and qualification", kind: "funnel", rows: [["AI", "reactivation · permission · intent · FAQs · qualification · follow-up"], ["HUMANS", "trust · nuance · negotiation · closure"]], caption: "At millions of leads, Aira can re-engage and screen every inquiry, routing only high-intent, consented opportunities to advisors.", source: "Proposed ASBL pilot workflow" },
  { n: 25, title: "Prototype → production voice system", kind: "rivets", body: ["session isolation", "telephony", "Do Not Call\n(DNC)", "human transfer", "SLOs", "load tests", "replay", "retention", "incident response"], caption: "A production agent is a reliable call system: every conversation must be safe, observable and recoverable at scale.", source: "Duet production-readiness audit" },
  { n: 26, title: "The opening: owned call data + multilingual frontier", kind: "steps", rows: [["100s hrs", "Recorded ASBL\nsales calls"], ["LEARN", "Consent-safe data\n→ real-call evals"], ["OPEN", "Multilingual + code-mixed\nreliability is still open"]], caption: "The advantage is the loop: data → evaluations → reliability—before anyone treats multilingual voice as solved.", source: "ASBL call-recording asset · Duet evaluation framework" },
  { n: 27, title: "The lesson", kind: "closing", body: ["Human is not a model.", "Human is the behaviour of the whole system."], caption: "Buy the best primitives. Own interaction state, evidence and the evaluation loop. Keep the research lane alive.", source: "Duet experiment conclusion" },
  { n: 28, title: "Appendix · research map", kind: "research", rows: [["Moshi", "two-stream full-duplex speech"], ["PersonaPlex", "role + voice conditioning"], ["FD-Bench", "293 conversations · 1,200 interruptions"], ["Turn-taking studies", "noise + decoding bias"], ["Duet", "guarded speculation + actions"]], source: "arXiv:2410.00037 · 2507.19040 · 2605.20356" },
  { n: 29, title: "Appendix · metrics that matter", kind: "metricgrid", rows: [["ASR", "WER / CER · accent · SNR · code-mix"], ["TURN", "endpoint · takeover · overlap · barge-stop"], ["REASON", "factuality · policy · task · TTFT"], ["TTS", "TTFB · MOS · intelligibility · glitches"], ["SYSTEM", "E2E p50/p95 · errors · cost/min"], ["BUSINESS", "qualified handoff · advisor time · visits"]], caption: "A production voice eval is layered. Measure recognition by accent and noise, turn-taking by endpoint and overlap, reasoning by factuality and task success, speech by TTFB and preference, and the whole system by tail latency, cost and business outcomes.", source: "Duet evaluation framework" },
  { n: 30, title: "Closing notes", kind: "questions", rows: [["Is this truly full duplex?", "Controlled duplex today; Moshi is the native research lane."], ["Why not one speech-to-speech model?", "Control, actions and deterministic policy still win here."], ["Why not a 20B local LLM?", "Re-test on production GPU against the same gates."], ["Can this call customers tomorrow?", "No—telephony, Do Not Call (DNC), isolation and transfer are P0."], ["What is defensible?", "Interaction state, eval data, workflows and reliability."]], source: "Duet engineering Q&A" },
  { n: 31, title: "Thank you", kind: "thanks", body: ["MS Sharat Chandra"], source: "Duet · Aira" },
];

function addShape(slide, geometry, left, top, width, height, fill = "none", lineFill = "none", lineWidth = 0, radius) {
  return slide.shapes.add({
    geometry,
    position: { left, top, width, height },
    fill,
    line: { style: "solid", fill: lineFill, width: lineWidth },
    ...(radius ? { borderRadius: radius } : {}),
  });
}

function addText(slide, text, left, top, width, height, size = 28, color = C.navy, options = {}) {
  const box = addShape(slide, "textbox", left, top, width, height, options.fill || "none", options.line || "none", options.lineWidth || 0, options.radius);
  box.text = text;
  box.text.style = {
    fontSize: size,
    color,
    bold: options.bold ?? false,
    alignment: options.align || "left",
    verticalAlignment: options.valign || "middle",
    autoFit: "shrinkText",
    typeface: options.mono ? MONO : FONT,
    insets: options.insets || { left: 0, right: 0, top: 0, bottom: 0 },
    ...(options.lineSpacing ? { lineSpacing: options.lineSpacing } : {}),
  };
  return box;
}

function line(slide, x1, y1, x2, y2, color = C.line, width = 2) {
  return addShape(
    slide,
    "line",
    Math.min(x1, x2),
    Math.min(y1, y2),
    Math.abs(x2 - x1),
    Math.abs(y2 - y1),
    "none",
    color,
    width,
  );
}

function pill(slide, text, left, top, width, color = C.cyan) {
  addText(slide, text, left, top, width, 34, 14, C.cream2, { fill: color, radius: 17, bold: true, align: "center" });
}

async function noteMap() {
  const md = await fs.readFile(SOURCE_MD, "utf8");
  const map = new Map();
  const re = /## Slide (\d+) — ([^\n]+)[\s\S]*?\*\*Speaker notes\*\*: ([\s\S]*?)(?=\n\n\*\*Source\*\*:|\n\n---)/g;
  for (const m of md.matchAll(re)) map.set(Number(m[1]), m[3].replace(/\n/g, " ").trim());
  map.set(28, "Moshi established a native two-stream speech architecture. PersonaPlex added role and voice conditioning. FD-Bench and newer turn-taking studies provide reproducible interaction tests. Duet's proposed contribution is modular guarded speculation plus capability-backed actions; novelty remains unproven until human ablations.");
  map.set(29, "A production voice eval is layered. Measure recognition by accent and noise, turn-taking by endpoint and overlap, reasoning by factuality and task success, speech by TTFB and preference, and the whole system by tail latency, cost and business outcomes.");
  map.set(30, "Use these answers to stay candid. Aira is controlled duplex, not a finished native speech model. It is a serious instrument and architecture prototype, not yet an outbound production dialer. The defensible asset is the interaction and evidence loop.");
  return map;
}

function addBackground(slide, bytes, idx, panel = true) {
  slide.images.add({ blob: bytes, contentType: "image/jpeg", alt: "Cream and cyan halftone landscape background", fit: "cover", position: { left: 0, top: 0, width: W, height: H } });
  if (panel) addShape(slide, "roundRect", 54, 42, 1172, 636, "#FFF8EA/92", "#FFFFFF/00", 0, 28);
  addText(slide, String(idx).padStart(2, "0"), 1166, 666, 54, 20, 10, C.muted, { mono: true, align: "right" });
}

function addHeader(slide, spec, kicker = "DUET · AIRA") {
  addText(slide, kicker, 78, 60, 320, 24, 11, C.cyan, { bold: true });
  addText(slide, spec.title, 78, 92, 1050, 76, 36, C.navy, { bold: true });
  line(slide, 78, 174, 1202, 174, C.line, 1);
}

function addFooter(slide, source) {
  addText(slide, source, 78, 666, 1000, 20, 9, C.muted, { mono: true });
}

function card(slide, title, body, x, y, w, h, accent = C.cyan) {
  addShape(slide, "roundRect", x, y, w, h, C.cream2, C.line, 1, 18);
  addShape(slide, "rect", x, y, 7, h, accent, accent, 0, 3);
  addText(slide, title, x + 24, y + 15, w - 42, 28, 14, accent, { bold: true });
  addText(slide, body, x + 24, y + 48, w - 42, h - 62, 19, C.navy, { bold: false, valign: "top" });
}

function render(spec, slide) {
  if (spec.kind === "hero") {
    addText(slide, "DUET / AIRA", 78, 78, 360, 28, 14, C.cyan, { bold: true });
    addText(slide, spec.title, 78, 162, 820, 180, 56, C.navy, { bold: true, lineSpacing: 0.94 });
    addText(slide, spec.body[1], 82, 372, 680, 80, 22, C.muted);
    line(slide, 82, 532, 1130, 532, C.cyan, 3);
    for (let i = 0; i < 22; i++) {
      const x = 82 + i * 48;
      const amp = 8 + (i % 5) * 6;
      line(slide, x, 532 - amp, x, 532 + amp, i % 4 === 0 ? C.coral : C.cyan, 2);
    }
    return;
  }
  if (spec.kind === "demo") {
    addText(slide, "LIVE DEMO", 78, 66, 250, 30, 13, C.cyan, { bold: true });
    addShape(slide, "roundRect", 126, 122, 1028, 516, "#FFF8EA/60", C.cyan, 3, 24);
    addText(slide, "DROP RECORDED DEMO HERE", 300, 318, 680, 64, 34, C.navy, { bold: true, align: "center" });
    addText(slide, "disclosure · grounded answer · interruption · action · decision trace", 280, 390, 720, 40, 16, C.muted, { align: "center" });
    return;
  }
  if (spec.kind === "thanks") {
    addText(slide, "DUET · AIRA", 78, 78, 360, 28, 14, C.cyan, { bold: true });
    addText(slide, "Thank you.", 120, 258, 1040, 92, 62, C.navy, { bold: true, align: "center" });
    addText(slide, spec.body[0], 160, 370, 960, 48, 28, C.coral, { bold: true, align: "center" });
    line(slide, 180, 540, 1100, 540, C.cyan, 3);
    for (let i = 0; i < 26; i++) {
      const x = 180 + i * 36;
      const amp = 6 + ((i * 13) % 22);
      line(slide, x, 540 - amp, x, 540 + amp, i > 11 && i < 15 ? C.coral : C.cyan, 2);
    }
    return;
  }

  addHeader(slide, spec);

  if (spec.kind === "orbit") {
    addText(slide, "ONE SHARED STATE", 78, 206, 220, 24, 11, C.coral, { bold: true });
    addShape(slide, "roundRect", 78, 232, 1124, 66, C.pale, C.line, 1, 18);
    addText(slide, "conversation state", 106, 243, 250, 28, 20, C.navy, { bold: true });
    addText(slide, "who owns the floor  ·  current intent  ·  cancellation version", 394, 243, 720, 28, 16, C.muted, { align: "right" });
    const stages = [
      { num: "01", title: "Listen", body: "capture speech\nand ownership", x: 78, color: C.cyan },
      { num: "02", title: "Decide", body: "facts · policy\nand planning", x: 444, color: C.coral },
      { num: "03", title: "Speak", body: "stream voice\nand stay cancellable", x: 810, color: C.teal },
    ];
    stages.forEach((stage) => {
      addShape(slide, "roundRect", stage.x, 332, 314, 124, C.cream2, C.line, 1.2, 18);
      addText(slide, stage.num, stage.x + 20, 352, 46, 18, 11, stage.color, { bold: true });
      addText(slide, stage.title, stage.x + 20, 374, 150, 30, 22, C.navy, { bold: true });
      addText(slide, stage.body, stage.x + 20, 407, 250, 34, 15, C.muted);
    });
    addText(slide, "→", 396, 369, 32, 42, 28, C.coral, { bold: true, align: "center" });
    addText(slide, "→", 762, 369, 32, 42, 28, C.coral, { bold: true, align: "center" });
    addText(slide, "CONTINUOUS CAPABILITIES", 78, 492, 270, 24, 11, C.cyan, { bold: true });
    addText(slide, "They run beside the turn—not after it.", 718, 492, 484, 24, 14, C.muted, { align: "right" });
    const capabilities = [
      { title: "Remember", body: "retain useful context", x: 78, color: C.cyan },
      { title: "Yield", body: "give the caller the floor", x: 444, color: C.coral },
      { title: "Act", body: "request safe next steps", x: 810, color: C.teal },
    ];
    capabilities.forEach((capability) => {
      addShape(slide, "roundRect", capability.x, 524, 314, 62, "#FFFFFF/55", C.line, 1, 16);
      addText(slide, capability.title, capability.x + 20, 534, 106, 22, 17, capability.color, { bold: true });
      addText(slide, capability.body, capability.x + 128, 534, 164, 22, 14, C.muted, { align: "right" });
    });
  } else if (spec.kind === "glossary") {
    addText(slide, "TERM", 92, 198, 186, 18, 10, C.cyan, { bold: true });
    addText(slide, "WHAT IT LITERALLY MEANS", 304, 198, 300, 18, 10, C.cyan, { bold: true });
    addText(slide, "IN A CONVERSATION", 636, 198, 444, 18, 10, C.cyan, { bold: true });
    spec.rows.forEach((r, i) => {
      const y = 222 + i * 52;
      addText(slide, r[0], 92, y, 186, 40, 14, C.cream2, { fill: i % 2 ? C.teal : C.cyan, radius: 15, bold: true, align: "center" });
      addText(slide, r[1], 304, y, 300, 40, 14, C.navy, { fill: "#FFFFFF/60", line: C.line, lineWidth: 1, radius: 14, insets: { left: 14, right: 10, top: 0, bottom: 0 } });
      addText(slide, r[2], 636, y, 444, 40, 17, C.navy, { fill: C.cream2, line: C.line, lineWidth: 1, radius: 14, insets: { left: 18, right: 10, top: 0, bottom: 0 } });
    });
  } else if (spec.kind === "waterfall") {
    const widths = [130, 130, 130, 255, 140, 145];
    const colors = [C.pale, "#DDEFF3", "#CBE8EE", C.coral, "#82BFD1", C.teal];
    let x = 90;
    spec.body.forEach((t, i) => {
      addShape(slide, "roundRect", x, 278, widths[i], 90, colors[i], colors[i], 0, 16);
      addText(slide, t, x + 8, 278, widths[i] - 16, 90, 17, i === 3 ? C.cream2 : C.navy, { bold: true, align: "center" });
      if (i < spec.body.length - 1) addText(slide, "+", x + widths[i] - 2, 300, 30, 40, 24, C.coral, { bold: true, align: "center" });
      x += widths[i] + 18;
    });
    addText(slide, "wait + wait + wait + wait", 280, 428, 720, 58, 35, C.coral, { mono: true, bold: true, align: "center" });
    addText(slide, "Measured rich-response median: 2,715 ms", 300, 510, 680, 44, 20, C.navy, { bold: true, align: "center" });
  } else if (spec.kind === "owners") {
    spec.body.forEach((t, i) => card(slide, `${String(i + 1).padStart(2, "0")}`, t, 82 + i * 286, 238, 248, 178, i === 1 ? C.coral : C.cyan));
    const failureModes = ["wait for enough\nsilence to hand off", "wait for stable intent\nand verified facts", "wait for a safe\nfirst clause", "wait for transport\nand device buffer"];
    failureModes.forEach((mode, i) => addText(slide, mode, 106 + i * 286, 336, 190, 44, 15, C.muted));
    addText(slide, "FAST MODELS LOSE AT THE HANDOFF", 160, 478, 960, 22, 11, C.coral, { bold: true, align: "center" });
    addText(slide, "Each component can be fast in isolation. The conversation waits until the next decision is safe to commit.", 150, 505, 980, 34, 20, C.navy, { bold: true, align: "center" });
    const boundaries = ["caller finished", "meaning stable", "safe first clause", "playable audio"];
    boundaries.forEach((label, i) => {
      const x = 166 + i * 246;
      addText(slide, label, x, 553, 188, 34, 14, C.navy, { fill: C.cream2, line: C.line, lineWidth: 1, radius: 15, bold: true, align: "center" });
      if (i < boundaries.length - 1) addText(slide, "→", x + 196, 550, 34, 40, 23, C.coral, { bold: true, align: "center" });
    });
    addText(slide, "The delay is in the boundary between engines—not only inside the engine.", 140, 598, 1000, 24, 15, C.muted, { align: "center" });
  } else if (spec.kind === "speculation") {
    addText(slide, "partial transcript", 90, 242, 210, 48, 18, C.navy, { fill: C.pale, radius: 18, bold: true, align: "center" });
    line(slide, 300, 266, 445, 266, C.line, 3);
    addText(slide, "quarantined\nspeculation", 445, 212, 240, 110, 22, C.cream2, { fill: C.cyan, radius: 20, bold: true, align: "center" });
    line(slide, 685, 266, 830, 266, C.line, 3);
    addText(slide, "final meaning\nconfirmed", 830, 212, 260, 110, 22, C.navy, { fill: C.cream2, line: C.teal, lineWidth: 3, radius: 20, bold: true, align: "center" });
    spec.body.forEach((t, i) => addText(slide, t, 140, 382 + i * 64, 1000, 46, 25, i === 2 ? C.coral : C.navy, { bold: true, align: "center" }));
  } else if (spec.kind === "lanes") {
    spec.rows.forEach((r, i) => {
      const y = 206 + i * 65;
      addText(slide, r[0], 84, y, 130, 42, 13, C.cream2, { fill: i === 2 ? C.coral : C.cyan, radius: 12, bold: true, align: "center" });
      line(slide, 238, y + 21, 1130, y + 21, i === 2 ? C.coral : C.line, i === 0 ? 4 : 2);
      addText(slide, r[1], 270 + (i > 1 ? i * 18 : 0), y - 1, 760, 44, 18, C.navy, { mono: true, fill: C.cream2, radius: 10, align: "center" });
    });
  } else if (spec.kind === "architecture") {
    const xs = [68, 238, 408, 618, 828, 1038];
    spec.body.forEach((t, i) => {
      const accent = i === 2 ? C.coral : (i === 3 ? C.teal : C.cyan);
      addShape(slide, "roundRect", xs[i], 286, 138, 90, i === 2 ? C.coral : C.cream2, accent, 2, 18);
      addText(slide, t, xs[i] + 8, 286, 122, 90, 18, i === 2 ? C.cream2 : C.navy, { bold: true, align: "center" });
      if (i < xs.length - 1) line(slide, xs[i] + 138, 331, xs[i + 1], 331, C.line, 3);
    });
    ["policy", "facts", "actions", "telemetry"].forEach((t, i) => pill(slide, t, 286 + i * 180, 470, 150, i === 0 ? C.coral : C.cyan));
  } else if (spec.kind === "waveforms") {
    const waves = [250, 455];
    spec.body.forEach((t, wi) => {
      addText(slide, wi === 0 ? "MEANING IN" : "TRUST OUT", 90, waves[wi] - 52, 180, 26, 12, wi === 0 ? C.cyan : C.teal, { bold: true });
      for (let i = 0; i < 38; i++) {
        const x = 95 + i * 28;
        const amp = 5 + ((i * 7 + wi * 3) % 28);
        line(slide, x, waves[wi] - amp, x, waves[wi] + amp, wi === 0 ? C.cyan : C.teal, 2);
      }
      addText(slide, t, 150, waves[wi] + 48, 980, 58, 22, C.navy, { bold: true, align: "center" });
    });
  } else if (spec.kind === "bars") {
    addText(slide, spec.label, 90, 204, 300, 36, 18, C.muted, { bold: true });
    const max = 15;
    spec.data.forEach((d, i) => {
      const y = 264 + i * 78;
      addText(slide, d[0], 92, y, 180, 42, 16, C.navy, { bold: true });
      addShape(slide, "roundRect", 282, y + 5, 780 * d[1] / max, 32, i === 3 ? C.teal : (i === 0 ? C.coral : C.cyan), "none", 0, 12);
      addText(slide, `${d[1]}%`, 1090, y, 90, 42, 18, i === 3 ? C.teal : C.navy, { mono: true, bold: true, align: "right" });
    });
    addText(slide, "In a noisy call, ASR choice determines what the agent believes before reasoning begins.", 130, 574, 1020, 42, 21, C.navy, { bold: true, align: "center" });
  } else if (spec.kind === "timeline") {
    addText(slide, spec.label, 90, 208, 300, 36, 18, C.muted, { bold: true });
    line(slide, 130, 358, 1135, 358, C.line, 5);
    [0, 100, 200, 300, 400, 500].forEach((v, i) => {
      const x = 130 + i * 201;
      line(slide, x, 346, x, 374, C.line, 2);
      addText(slide, `${v} ms`, x - 35, 390, 70, 24, 11, C.muted, { mono: true, align: "center" });
    });
    spec.data.forEach((d, i) => {
      const x = 130 + d[1] * 2.01;
      addShape(slide, "ellipse", x - 13, 345, 26, 26, i === 1 ? C.teal : (i === 0 ? C.coral : C.cyan), "none", 0);
      addText(slide, `${d[0]}\n${d[1]} ms`, x - 100, 250 + (i % 2) * 160, 200, 70, 17, C.navy, { bold: true, align: "center" });
      line(slide, x, 320 + (i % 2) * 65, x, 345, i === 1 ? C.teal : C.cyan, 2);
    });
    addText(slide, "Fast speech start ≠ human voice quality", 250, 540, 780, 50, 28, C.coral, { bold: true, align: "center" });
  } else if (spec.kind === "quadrant") {
    addText(slide, "MEASURED ON OUR APPLE M5 · NOT A UNIVERSAL MODEL RANKING", 78, 202, 720, 22, 11, C.coral, { bold: true });
    addText(slide, "Evidence level: 0 failed control  ·  1 relevant but ungated  ·  2 grounded sample  ·  3 132/136 checks", 78, 228, 1100, 24, 14, C.muted);
    const left = 250;
    const right = 1130;
    const top = 310;
    const bottom = 570;
    const yFor = (level) => bottom - level * (bottom - top) / 3;
    const xFor = (ms) => left + ms * (right - left) / 3200;
    for (let level = 0; level <= 3; level += 1) {
      const y = yFor(level);
      line(slide, left, y, right, y, level === 0 ? C.navy : C.line, level === 0 ? 2 : 1);
      addText(slide, String(level), 184, y - 12, 32, 24, 13, C.navy, { mono: true, bold: true, align: "right" });
    }
    line(slide, left, top, left, bottom, C.navy, 2);
    addText(slide, "GROUNDING / POLICY EVIDENCE ↑", 250, 284, 260, 18, 11, C.cyan, { bold: true });
    addText(slide, "0  known failure", 78, 550, 140, 18, 11, C.muted);
    addText(slide, "3  evaluated gate", 78, 316, 140, 18, 11, C.muted);
    [0, 800, 1600, 2400, 3200].forEach((ms) => {
      const x = xFor(ms);
      line(slide, x, bottom, x, bottom + 8, C.navy, 1);
      addText(slide, `${ms.toLocaleString()} ms`, x - 44, 582, 88, 20, 11, C.muted, { mono: true, align: "center" });
    });
    addText(slide, "FIRST-PLAN LATENCY →", 778, 608, 352, 22, 11, C.cyan, { bold: true, align: "right" });
    const points = [
      { name: "Qwen 0.8B", detail: "153 ms · fabricated facts", ms: 153, level: 0, color: C.coral, dx: 10, dy: -42, w: 195 },
      { name: "Gemma 1B", detail: "760–1,750 ms · schema/policy fails", ms: 1255, level: 0, color: C.coral, dx: -154, dy: -70, w: 260 },
      { name: "Qwen 4B", detail: "1,623 ms · relevant, ungated", ms: 1623, level: 1, color: C.cyan, dx: 10, dy: -50, w: 225 },
      { name: "Gemma 4B", detail: "2,858–3,142 ms · grounded sample", ms: 3000, level: 2, color: C.teal, dx: -248, dy: -45, w: 240 },
      { name: "Gemini Flash Lite", detail: "1,120 ms · 132/136 checks", ms: 1120, level: 3, color: C.teal, dx: 14, dy: -38, w: 260, highlight: true },
    ];
    points.forEach((point) => {
      const x = xFor(point.ms);
      const y = yFor(point.level);
      const size = point.highlight ? 26 : 18;
      addShape(slide, "ellipse", x - size / 2, y - size / 2, size, size, point.color, C.cream2, point.highlight ? 3 : 1.5);
      addText(slide, point.name, x + point.dx, y + point.dy, point.w, 20, 15, C.navy, { bold: true });
      addText(slide, point.detail, x + point.dx, y + point.dy + 20, point.w, 22, 12, C.muted);
    });
    addText(slide, "Gemini was the only option that paired ~1.1 s planning with a gated grounded-response eval.", 156, 632, 968, 22, 15, C.navy, { bold: true, align: "center" });
  } else if (spec.kind === "modeltable") {
    const headers = ["MODEL", "FIRST-PLAN LATENCY", "OUTCOME"];
    const col = [82, 394, 610, 1200];
    headers.forEach((h, i) => addText(slide, h, col[i] + 14, 212, col[i + 1] - col[i] - 28, 36, 12, C.cyan, { bold: true }));
    spec.rows.forEach((r, i) => {
      const y = 246 + i * 70;
      const chosen = i === spec.rows.length - 1;
      addShape(slide, "roundRect", 82, y, 1118, 58, chosen ? "#DDEEEA" : C.cream2, chosen ? C.teal : C.line, chosen ? 2 : 1, 14);
      addText(slide, r[0], 100, y, 276, 58, 16, chosen ? C.teal : C.navy, { bold: true });
      addText(slide, r[1], 408, y, 180, 58, 15, chosen ? C.teal : C.navy, { mono: true, bold: true });
      addText(slide, r[2], 625, y, 550, 58, 16, chosen ? C.teal : (i === 0 || i === 2 ? C.coral : C.navy), { bold: chosen || i === 0 || i === 2 });
    });
    addText(slide, "Chosen: ~1.1 s planning + 132/136 grounded-policy checks.", 150, 616, 980, 26, 16, C.teal, { bold: true, align: "center" });
  } else if (spec.kind === "compare") {
    const x = [92, 390, 658, 876, 1105];
    spec.rows.forEach((r, ri) => {
      const y = 232 + ri * 94;
      r.forEach((v, ci) => addText(slide, v, x[ci] + 8, y, x[ci + 1] - x[ci] - 16, 68, ri === 0 ? 14 : 21, ri === 0 ? C.cyan : C.navy, { bold: true, align: ci === 0 ? "left" : "center", fill: ri === 0 ? "none" : (ri === 1 ? "#E6F2F5" : C.cream2), radius: ri === 0 ? 0 : 12 }));
    });
    addText(slide, "fast", 170, 555, 100, 28, 14, C.teal, { bold: true });
    line(slide, 260, 570, 1020, 570, C.line, 3);
    addText(slide, "polite", 1020, 555, 100, 28, 14, C.teal, { bold: true, align: "right" });
    addShape(slide, "ellipse", 355, 556, 28, 28, C.coral, "none", 0);
    addText(slide, "Moshi", 322, 592, 95, 24, 12, C.coral, { bold: true, align: "center" });
    addText(slide, spec.body, 160, 622, 960, 24, 15, C.navy, { bold: true, align: "center" });
  } else if (spec.kind === "nearbars") {
    const [thesis, expected, result, verdict] = spec.body;
    addShape(slide, "roundRect", 82, 210, 536, 108, C.cream2, C.line, 1, 16);
    addText(slide, "THE THESIS", 106, 228, 180, 20, 12, C.cyan, { bold: true });
    addText(slide, thesis, 106, 254, 476, 44, 17, C.navy, { bold: true });
    addShape(slide, "roundRect", 662, 210, 536, 108, "#E8F3F6", C.line, 1, 16);
    addText(slide, "WHAT WE EXPECTED", 686, 228, 220, 20, 12, C.cyan, { bold: true });
    addText(slide, expected, 686, 254, 476, 44, 17, C.navy, { bold: true });

    addShape(slide, "roundRect", 82, 350, 1116, 168, "#F6FBFC", C.line, 1, 18);
    addText(slide, "BASELINE", 112, 374, 220, 20, 12, C.muted, { bold: true });
    addText(slide, `${spec.data[0][1].toLocaleString()} ms`, 112, 402, 300, 44, 30, C.navy, { mono: true, bold: true });
    addText(slide, "wait for four stable words", 112, 452, 320, 26, 15, C.muted);
    line(slide, 528, 378, 528, 490, C.line, 1);
    addText(slide, "TWO-WORD SPECULATION", 566, 374, 270, 20, 12, C.teal, { bold: true });
    addText(slide, `${spec.data[1][1].toLocaleString()} ms`, 566, 402, 300, 44, 30, C.teal, { mono: true, bold: true });
    addText(slide, "start from two stable words", 566, 452, 300, 26, 15, C.muted);
    addText(slide, "31 ms", 930, 390, 200, 40, 28, C.coral, { mono: true, bold: true, align: "center", fill: C.cream2, radius: 16 });
    addText(slide, result, 890, 438, 280, 30, 14, C.muted, { bold: true, align: "center" });

    addShape(slide, "roundRect", 190, 558, 900, 64, "#FCEAE6", "none", 0, 16);
    addText(slide, "HONEST VERDICT", 214, 576, 160, 20, 12, C.coral, { bold: true });
    addText(slide, verdict, 392, 570, 660, 32, 17, C.navy, { bold: true, align: "center" });
  } else if (spec.kind === "inversion") {
    addText(slide, spec.body[0], 120, 244, 400, 104, 30, C.cream2, { fill: C.teal, radius: 24, bold: true, align: "center" });
    addText(slide, "PROXY ✓", 235, 214, 170, 24, 12, C.teal, { bold: true, align: "center" });
    line(slide, 520, 296, 710, 296, C.coral, 5);
    addText(slide, "→", 610, 262, 60, 60, 44, C.coral, { bold: true, align: "center" });
    addText(slide, "REALITY ✕", 824, 214, 180, 24, 12, C.coral, { bold: true, align: "center" });
    spec.body.slice(1).forEach((t, i) => addText(slide, t, 730, 246 + i * 104, 390, 72, 25, C.cream2, { fill: C.coral, radius: 18, bold: true, align: "center" }));
    addText(slide, spec.caption, 160, 568, 960, 34, 20, C.navy, { bold: true, align: "center" });
    addText(slide, spec.lesson, 160, 612, 960, 30, 15, C.teal, { bold: true, align: "center", fill: "#E8F3F6", radius: 14 });
  } else if (spec.kind === "loop") {
    const pts = [[130, 290], [390, 220], [700, 220], [960, 290]];
    spec.body.forEach((t, i) => {
      addShape(slide, "ellipse", pts[i][0], pts[i][1], 190, 110, i === 3 ? C.teal : C.pale, i === 3 ? C.teal : C.cyan, 2);
      addText(slide, t, pts[i][0] + 12, pts[i][1], 166, 110, 21, C.navy, { bold: true, align: "center" });
    });
    addText(slide, "→", 330, 275, 60, 48, 30, C.cyan, { bold: true, align: "center" });
    addText(slide, "→", 625, 235, 60, 48, 30, C.cyan, { bold: true, align: "center" });
    addText(slide, "→", 895, 275, 60, 48, 30, C.cyan, { bold: true, align: "center" });
    line(slide, 1055, 400, 1055, 510, C.line, 3);
    line(slide, 1055, 510, 220, 510, C.line, 3);
    line(slide, 220, 510, 220, 400, C.line, 3);
    addText(slide, "real call", 520, 480, 240, 58, 25, C.coral, { fill: C.cream2, radius: 18, bold: true, align: "center" });
    addText(slide, spec.caption, 170, 590, 940, 34, 17, C.navy, { fill: "#E8F3F6", radius: 16, bold: true, align: "center" });
  } else if (spec.kind === "guard") {
    addShape(slide, "ellipse", 440, 246, 400, 280, C.cream2, C.coral, 6);
    addShape(slide, "ellipse", 535, 315, 210, 140, C.pale, C.cyan, 3);
    addText(slide, "LLM", 555, 344, 170, 82, 30, C.navy, { bold: true, align: "center" });
    const pts = [[120, 236], [130, 474], [520, 558], [930, 470], [930, 236]];
    spec.body.forEach((t, i) => pill(slide, t, pts[i][0], pts[i][1], 190, i === 1 ? C.coral : C.cyan));
    addText(slide, "Deterministic code", 487, 244, 306, 36, 15, C.coral, { bold: true, align: "center" });
    addText(slide, spec.caption, 150, 614, 980, 32, 16, C.navy, { fill: "#E8F3F6", radius: 16, bold: true, align: "center" });
  } else if (spec.kind === "observability") {
    addShape(slide, "ellipse", 530, 282, 220, 150, C.coral, "none", 0);
    addText(slide, "TRACE ID", 558, 315, 164, 84, 25, C.cream2, { mono: true, bold: true, align: "center" });
    const pts = [[92, 220], [810, 220], [92, 470], [810, 470]];
    spec.body.forEach((item, i) => {
      const [index, title, why] = item;
      const [x, y] = pts[i];
      const accent = i === 0 ? C.teal : C.cyan;
      addShape(slide, "roundRect", x, y, 300, 118, C.cream2, C.line, 1, 18);
      addShape(slide, "rect", x, y, 7, 118, accent, accent, 0, 3);
      addText(slide, index, x + 24, y + 15, 38, 20, 12, accent, { bold: true });
      addText(slide, title, x + 24, y + 43, 252, 28, 18, C.navy, { bold: true });
      addText(slide, why, x + 24, y + 78, 252, 22, 13, C.muted, { bold: true });
    });
    line(slide, 392, 279, 485, 279, C.line, 2); line(slide, 485, 279, 485, 357, C.line, 2); line(slide, 485, 357, 530, 357, C.line, 2);
    line(slide, 810, 279, 795, 279, C.line, 2); line(slide, 795, 279, 795, 357, C.line, 2); line(slide, 795, 357, 750, 357, C.line, 2);
    line(slide, 392, 529, 485, 529, C.line, 2); line(slide, 485, 529, 485, 357, C.line, 2);
    line(slide, 810, 529, 795, 529, C.line, 2); line(slide, 795, 529, 795, 357, C.line, 2);
    addText(slide, spec.caption, 150, 590, 980, 28, 16, C.navy, { fill: "#E8F3F6", radius: 15, bold: true, align: "center" });
    addText(slide, spec.subcaption, 300, 626, 680, 20, 13, C.muted, { bold: true, align: "center" });
  } else if (spec.kind === "run") {
    spec.data.forEach((d, i) => card(slide, d[0], d[1], 84 + i * 280, 242, 246, 154, i === 0 ? C.teal : C.cyan));
    line(slide, 112, 480, 1120, 480, C.line, 3);
    [230, 520, 795].forEach((x) => { addShape(slide, "ellipse", x, 466, 28, 28, C.coral, "none", 0); addText(slide, "cancel", x - 35, 510, 98, 24, 11, C.coral, { mono: true, align: "center" }); });
    [380, 935].forEach((x) => { addShape(slide, "diamond", x, 462, 38, 38, C.teal, "none", 0); addText(slide, "action", x - 30, 510, 98, 24, 11, C.teal, { mono: true, align: "center" }); });
    addText(slide, spec.body[0], 150, 588, 980, 34, 17, C.navy, { fill: "#E8F3F6", radius: 16, bold: true, align: "center" });
  } else if (spec.kind === "vendorbars") {
    const max = 2400;
    spec.data.forEach((d, i) => {
      const y = 245 + i * 112;
      addText(slide, d[0], 86, y, 210, 46, 17, C.navy, { bold: true });
      const width = 760 * d[1] / max;
      addShape(slide, "roundRect", 306, y + 6, width, 32, i === 1 ? C.coral : (i === 0 ? C.teal : C.cyan), "none", 0, 12);
      addText(slide, i === 1 ? "1.62–2.90 s" : `${d[1]} ms`, 1080, y, 110, 42, 17, C.navy, { mono: true, bold: true, align: "right" });
      addText(slide, d[2], 306, y + 50, 760, 26, 12, C.muted, { mono: true });
    });
    addText(slide, "NOT YET APPLES-TO-APPLES", 360, 592, 560, 40, 22, C.coral, { bold: true, align: "center" });
  } else if (spec.kind === "numbers") {
    spec.data.forEach((d, i) => {
      const x = 86 + (i % 2) * 555;
      const y = 220 + Math.floor(i / 2) * 190;
      addText(slide, d[0], x, y, 240, 92, 44, i === 1 ? C.teal : C.cyan, { mono: true, bold: true });
      addText(slide, d[1], x + 220, y + 6, 310, 72, 20, C.navy, { bold: true });
      line(slide, x, y + 112, x + 500, y + 112, C.line, 1);
    });
    addText(slide, spec.caption, 125, 592, 1030, 46, 15, C.navy, { fill: "#E8F3F6", radius: 16, bold: true, align: "center" });
  } else if (spec.kind === "funnel") {
    const widths = [900, 680, 460, 250];
    const ys = [218, 300, 382, 464];
    widths.forEach((w, i) => addShape(slide, "roundRect", 640 - w / 2, ys[i], w, 60, i < 3 ? "#DDEFF3" : C.teal, i < 3 ? C.cyan : C.teal, 1, 16));
    addText(slide, "AI", 176, 236, 90, 32, 15, C.cyan, { bold: true, align: "center" });
    addText(slide, spec.rows[0][1], 310, 226, 660, 40, 18, C.navy, { bold: true, align: "center" });
    addText(slide, "HUMAN ADVISOR", 495, 478, 290, 34, 15, C.cream2, { bold: true, align: "center" });
    addText(slide, spec.rows[1][1], 330, 555, 620, 40, 21, C.navy, { bold: true, align: "center" });
    addText(slide, spec.caption, 125, 610, 1030, 30, 15, C.navy, { fill: "#E8F3F6", radius: 15, bold: true, align: "center" });
  } else if (spec.kind === "rivets") {
    // Connectors are drawn first and stop at each circle edge, so they read as links rather than crossing nodes.
    [[150, 310], [372, 532], [594, 754], [816, 976]].forEach(([from, to]) => line(slide, from, 257, to, 257, C.line, 2));
    [[150, 310], [372, 532], [594, 754]].forEach(([from, to]) => line(slide, from, 415, to, 415, C.line, 2));
    spec.body.forEach((t, i) => {
      const x = 88 + (i % 5) * 222;
      const y = 226 + Math.floor(i / 5) * 158;
      addShape(slide, "ellipse", x, y, 62, 62, i === 8 ? C.coral : C.cyan, "none", 0);
      addText(slide, String(i + 1), x, y, 62, 62, 17, C.cream2, { mono: true, bold: true, align: "center" });
      addText(slide, t, x - 28, y + 78, 118, 50, 14, C.navy, { bold: true, align: "center" });
    });
    addText(slide, spec.caption, 150, 595, 980, 38, 17, C.navy, { fill: "#E8F3F6", radius: 16, bold: true, align: "center" });
  } else if (spec.kind === "steps") {
    spec.rows.forEach((r, i) => {
      const x = 120 + i * 362;
      const y = 410 - i * 82;
      addShape(slide, "roundRect", x, y, 300, 142, i === 2 ? C.teal : C.cream2, i === 2 ? C.teal : C.cyan, 2, 24);
      addText(slide, r[0], x + 24, y + 18, 130, 28, 15, i === 2 ? C.cream2 : C.cyan, { mono: true, bold: true });
      addText(slide, r[1], x + 24, y + 52, 252, 72, 20, i === 2 ? C.cream2 : C.navy, { bold: true, align: "center" });
    });
    addText(slide, spec.caption, 150, 590, 980, 36, 16, C.navy, { fill: "#E8F3F6", radius: 16, bold: true, align: "center" });
  } else if (spec.kind === "closing") {
    addText(slide, spec.body[0], 120, 224, 1040, 92, 46, C.navy, { bold: true, align: "center" });
    addText(slide, spec.body[1], 160, 340, 960, 122, 38, C.coral, { bold: true, align: "center" });
    addText(slide, spec.caption, 150, 474, 980, 34, 16, C.navy, { fill: "#E8F3F6", radius: 16, bold: true, align: "center" });
    line(slide, 180, 548, 1100, 548, C.cyan, 3);
    for (let i = 0; i < 26; i++) {
      const x = 180 + i * 36;
      const amp = 6 + ((i * 11) % 24);
      line(slide, x, 548 - amp, x, 548 + amp, i > 11 && i < 15 ? C.coral : C.cyan, 2);
    }
  } else if (spec.kind === "research") {
    spec.rows.forEach((r, i) => {
      const y = 215 + i * 80;
      addText(slide, r[0], 90, y, 240, 56, 16, C.cream2, { fill: i === 4 ? C.coral : C.cyan, radius: 16, bold: true, align: "center" });
      addText(slide, r[1], 360, y, 760, 56, 19, C.navy, { fill: C.cream2, line: C.line, lineWidth: 1, radius: 16, insets: { left: 20, right: 10, top: 0, bottom: 0 } });
      if (i < spec.rows.length - 1) line(slide, 210, y + 56, 210, y + 80, C.line, 2);
    });
  } else if (spec.kind === "metricgrid") {
    spec.rows.forEach((r, i) => {
      const x = 84 + (i % 2) * 560;
      const y = 214 + Math.floor(i / 2) * 132;
      card(slide, r[0], r[1], x, y, 520, 104, i === 3 ? C.teal : C.cyan);
    });
    addText(slide, spec.caption, 110, 602, 1060, 42, 14, C.navy, { fill: "#E8F3F6", radius: 15, bold: true, align: "center" });
  } else if (spec.kind === "questions") {
    spec.rows.forEach((r, i) => {
      const y = 202 + i * 86;
      addText(slide, r[0], 88, y, 360, 62, 17, C.cream2, { fill: i === 3 ? C.coral : C.cyan, radius: 16, bold: true, align: "center" });
      addText(slide, r[1], 476, y, 700, 62, 17, C.navy, { fill: C.cream2, line: C.line, lineWidth: 1, radius: 16, insets: { left: 18, right: 12, top: 0, bottom: 0 } });
    });
  }
}

async function writeBlob(filePath, blob) {
  await fs.writeFile(filePath, new Uint8Array(await blob.arrayBuffer()));
}

async function main() {
  await fs.mkdir(RENDER_DIR, { recursive: true });
  await fs.mkdir(path.dirname(OUT), { recursive: true });
  const bgBytes = await Promise.all(BG.map((p) => fs.readFile(p)));
  const notes = await noteMap();
  const deck = Presentation.create({ slideSize: { width: W, height: H } });

  for (const spec of specs) {
    const slide = deck.slides.add();
    addBackground(slide, bgBytes[(spec.n - 1) % 4], spec.n, spec.kind !== "hero" && spec.kind !== "demo" && spec.kind !== "closing" && spec.kind !== "thanks");
    render(spec, slide);
    addFooter(slide, spec.source);
    const noteText = `${notes.get(spec.n) || "Use the visible slide as the discussion prompt."}\n\nSOURCES\n- ${spec.source}\n- Full source notes: docs/talk/FINAL_DECK_2026-08-25.md`;
    slide.speakerNotes.textFrame.setText(noteText);
    slide.speakerNotes.setVisible(true);
  }

  for (const [i, slide] of deck.slides.items.entries()) {
    const stem = `slide-${String(i + 1).padStart(2, "0")}`;
    await writeBlob(path.join(RENDER_DIR, `${stem}.png`), await deck.export({ slide, format: "png", scale: 1 }));
    const layout = await slide.export({ format: "layout" });
    await fs.writeFile(path.join(RENDER_DIR, `${stem}.layout.json`), await layout.text());
  }
  await writeBlob(path.join(RENDER_DIR, "deck-montage.webp"), await deck.export({ format: "webp", montage: true, scale: 0.45 }));
  const pptx = await PresentationFile.exportPptx(deck);
  await pptx.save(OUT);
  console.log(JSON.stringify({ out: OUT, renderDir: RENDER_DIR, slides: specs.length }, null, 2));
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
