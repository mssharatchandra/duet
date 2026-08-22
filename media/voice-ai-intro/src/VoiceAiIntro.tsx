import {
  AbsoluteFill,
  Easing,
  Interactive,
  interpolate,
  interpolateColors,
  useCurrentFrame,
} from "remotion";

const clamp = {extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const};

const phases = [
  {
    start: 0,
    end: 180,
    label: "THE OLD ARCHITECTURE",
    accent: "#d9ff66",
    lines: ["Why does voice AI", "still feel robotic?"],
    body: ["Not because every component is bad.", "Because they are connected like a queue."],
  },
  {
    start: 180,
    end: 360,
    label: "THE WAITING TAX",
    accent: "#ff765e",
    lines: ["You finish speaking.", "The pipeline starts waiting."],
    body: ["Silence detection, transcription, reasoning", "and speech generation happen in sequence."],
  },
  {
    start: 360,
    end: 570,
    label: "BOUNDARY 01 · ASR",
    accent: "#f4b84a",
    lines: ["The words can be right.", "The meaning can be wrong."],
    body: ["WER measures the transcript.", "Humans listen to the person."],
  },
  {
    start: 570,
    end: 780,
    label: "BOUNDARY 02 · TTS",
    accent: "#b89cff",
    lines: ["A correct sentence", "can still feel wrong."],
    body: ["Tone, timing and restraint decide whether", "a response feels caring or dismissive."],
  },
  {
    start: 780,
    end: 990,
    label: "THE SOCIAL LAYER",
    accent: "#f4b84a",
    lines: ["Conversation is not", "two clean turns."],
    body: ["We overlap, pause, interrupt and signal", "that we are listening while someone speaks."],
  },
  {
    start: 990,
    end: 1200,
    label: "THE ARCHITECTURAL SHIFT",
    accent: "#65d8ff",
    lines: ["Stop passing turns.", "Keep two streams alive."],
    body: ["A full duplex system can listen and speak", "at the same time, like a phone call."],
  },
  {
    start: 1200,
    end: 1440,
    label: "GPT-LIVE · THE SIGNAL",
    accent: "#65d8ff",
    lines: ["The fast voice stays present.", "The slow brain goes deeper."],
    body: ["GPT-Live keeps the conversation moving", "while GPT-5.5 handles harder work."],
  },
  {
    start: 1440,
    end: 1680,
    label: "WHAT I AM EXPLORING",
    accent: "#d9ff66",
    lines: ["Faster speech is not enough.", "The system must stay coherent."],
    body: ["The goal is natural conversational timing", "without losing meaning or control."],
  },
];

const phaseOpacity = (frame: number, start: number, end: number) =>
  interpolate(frame, [start - 4, start + 4, end - 4, end + 4], [0, 1, 1, 0], {
    ...clamp,
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });

const Waveform: React.FC<{
  frame: number;
  color: string;
  width: number;
  height: number;
  quiet?: boolean;
  offset?: number;
}> = ({frame, color, width, height, quiet = false, offset = 0}) => {
  const bars = Array.from({length: Math.min(42, Math.max(18, Math.floor(width / 12)))});
  return (
    <div style={{width, height, display: "flex", alignItems: "center", gap: 5}}>
      {bars.map((_, index) => {
        const wave = Math.abs(Math.sin((index + frame * 0.45 + offset) * 0.51));
        const envelope = 0.35 + Math.abs(Math.sin((index + offset) * 0.19)) * 0.65;
        return (
          <div
            key={index}
            style={{
              width: 7,
              height: quiet ? 4 + wave * 5 : 8 + wave * height * 0.78 * envelope,
              borderRadius: 999,
              backgroundColor: color,
              opacity: quiet ? 0.3 : 0.58 + wave * 0.42,
            }}
          />
        );
      })}
    </div>
  );
};

const PipelineVisual: React.FC<{frame: number}> = ({frame}) => {
  const stages = [
    {label: "MIC", color: "#d9ff66"},
    {label: "VAD", color: "#ff765e"},
    {label: "ASR", color: "#f4b84a"},
    {label: "LLM", color: "#65d8ff"},
    {label: "TTS", color: "#b89cff"},
    {label: "VOICE", color: "#d9ff66"},
  ];
  return (
    <div style={{position: "absolute", inset: 0}}>
      <div style={{position: "absolute", left: 44, top: 78, fontFamily: "DM Mono, monospace", fontSize: 22, letterSpacing: "0.1em", color: "rgba(255,255,255,.52)"}}>THE STACK EVERYONE RUNS</div>
      <div style={{position: "absolute", left: 44, right: 44, top: 185, display: "flex", alignItems: "center", justifyContent: "space-between"}}>
        {stages.map((stage, index) => {
          const active = interpolate(frame, [28 + index * 15, 40 + index * 15, 80 + index * 15, 94 + index * 15], [0.18, 1, 1, 0.25], clamp);
          return (
            <div key={stage.label} style={{display: "flex", alignItems: "center"}}>
              <div
                style={{
                  width: 116,
                  height: 116,
                  borderRadius: 28,
                  border: `2px solid ${stage.color}`,
                  backgroundColor: `${stage.color}${active > 0.5 ? "22" : "08"}`,
                  boxShadow: `0 0 ${active * 36}px ${stage.color}33`,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: stage.color,
                  fontFamily: "DM Mono, monospace",
                  fontSize: 24,
                  fontWeight: 500,
                }}
              >
                {stage.label}
              </div>
              {index < stages.length - 1 ? <div style={{width: 40, height: 2, backgroundColor: "rgba(255,255,255,.22)"}} /> : null}
            </div>
          );
        })}
      </div>
      <div style={{position: "absolute", left: 48, right: 48, top: 345, display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10}}>
        {[
          ["VAD", "voice activity detection"],
          ["ASR", "automatic speech recognition"],
          ["LLM", "language model"],
          ["TTS", "text to speech"],
        ].map(([short, meaning]) => (
          <div key={short} style={{padding: "14px 15px", borderRadius: 15, border: "1px solid rgba(255,255,255,.13)", backgroundColor: "rgba(255,255,255,.025)"}}>
            <div style={{fontFamily: "DM Mono, monospace", fontSize: 17, color: "#f5f1e7"}}>{short}</div>
            <div style={{fontSize: 17, lineHeight: 1.15, color: "rgba(255,255,255,.5)", marginTop: 7}}>{meaning}</div>
          </div>
        ))}
      </div>
      <div style={{position: "absolute", left: 52, right: 52, top: 510, padding: "30px 38px", borderRadius: 28, border: "1px solid rgba(255,255,255,.18)", backgroundColor: "rgba(255,255,255,.03)"}}>
        <Waveform frame={frame} color="#d9ff66" width={780} height={118} />
      </div>
      <div style={{position: "absolute", left: 52, bottom: 54, color: "rgba(255,255,255,.6)", fontSize: 30, lineHeight: 1.25}}>Every box works.<br /><span style={{color: "#d9ff66"}}>The composition creates the robot.</span></div>
    </div>
  );
};

const CascadeTimingVisual: React.FC<{frame: number}> = ({frame}) => {
  const local = frame - 180;
  const stages = [
    {label: "VAD", ms: 700, color: "#ff765e", detail: "waits for silence"},
    {label: "ASR", ms: 200, color: "#f4b84a", detail: "locks the transcript"},
    {label: "LLM", ms: 600, color: "#65d8ff", detail: "starts reasoning"},
    {label: "TTS", ms: 200, color: "#b89cff", detail: "starts speaking"},
  ];
  const total = 1700;
  const fill = interpolate(local, [24, 155], [0, 1], clamp);
  let running = 0;
  return (
    <div style={{position: "absolute", inset: 0}}>
      <div style={{position: "absolute", left: 48, top: 54, display: "flex", alignItems: "baseline", gap: 20}}>
        <div style={{fontFamily: "Instrument Serif, Georgia, serif", fontSize: 110, color: "#ff765e", letterSpacing: "-0.04em"}}>1.7s</div>
        <div style={{fontSize: 34, color: "rgba(255,255,255,.7)"}}>of dead air after you finish</div>
      </div>
      <div style={{position: "absolute", left: 48, right: 48, top: 220}}>
        <div style={{height: 120, display: "flex", borderRadius: 22, overflow: "hidden", backgroundColor: "rgba(255,255,255,.05)"}}>
          {stages.map((stage) => {
            const stageStart = running / total;
            running += stage.ms;
            const stageEnd = running / total;
            const revealed = interpolate(fill, [stageStart, stageEnd], [0, 1], clamp);
            return (
              <div key={stage.label} style={{position: "relative", width: `${(stage.ms / total) * 100}%`, borderRight: "2px solid #101714", backgroundColor: `${stage.color}16`}}>
                <div style={{position: "absolute", inset: 0, width: `${revealed * 100}%`, backgroundColor: stage.color, opacity: 0.9}} />
                <div style={{position: "absolute", left: stage.ms <= 200 ? 13 : 20, top: 20, color: revealed > 0.55 ? "#101714" : stage.color, fontFamily: "DM Mono, monospace", fontSize: stage.ms <= 200 ? 18 : 20, fontWeight: 600}}>{stage.label}</div>
                <div style={{position: "absolute", left: stage.ms <= 200 ? 13 : 20, bottom: 18, color: revealed > 0.55 ? "rgba(16,23,20,.75)" : "rgba(255,255,255,.58)", fontSize: stage.ms <= 200 ? 20 : 24}}>{stage.ms}<span style={{fontSize: 16}}> ms</span></div>
              </div>
            );
          })}
        </div>
        <div style={{display: "flex", marginTop: 24}}>
          {stages.map((stage) => (
            <div key={stage.detail} style={{width: `${(stage.ms / total) * 100}%`, paddingLeft: stage.ms <= 200 ? 9 : 18, color: "rgba(255,255,255,.55)", fontSize: stage.ms <= 200 ? 17 : 21, lineHeight: 1.12}}>{stage.detail}</div>
          ))}
        </div>
      </div>
      <div style={{position: "absolute", left: 48, right: 48, top: 455, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24}}>
        <div style={{padding: "34px 36px", borderRadius: 24, border: "1px solid rgba(255,118,94,.45)", backgroundColor: "rgba(255,118,94,.07)"}}>
          <div style={{fontFamily: "DM Mono, monospace", fontSize: 20, color: "#ff765e"}}>TYPICAL CASCADE</div>
          <div style={{fontFamily: "Instrument Serif, Georgia, serif", fontSize: 70, marginTop: 12}}>~1.7 sec</div>
          <div style={{fontSize: 25, color: "rgba(255,255,255,.58)"}}>four waits, paid in sequence</div>
        </div>
        <div style={{padding: "34px 36px", borderRadius: 24, border: "1px solid rgba(217,255,102,.45)", backgroundColor: "rgba(217,255,102,.06)"}}>
          <div style={{fontFamily: "DM Mono, monospace", fontSize: 20, color: "#d9ff66"}}>HUMAN CONVERSATION</div>
          <div style={{fontFamily: "Instrument Serif, Georgia, serif", fontSize: 70, marginTop: 12}}>~200 ms</div>
          <div style={{fontSize: 25, color: "rgba(255,255,255,.58)"}}>and often overlapping</div>
        </div>
      </div>
    </div>
  );
};

const SocialTimingVisual: React.FC<{frame: number}> = ({frame}) => {
  const local = frame - 780;
  const cursor = interpolate(local, [15, 135], [70, 885], clamp);
  return (
    <div style={{position: "absolute", inset: 0}}>
      <div style={{position: "absolute", left: 50, top: 58, color: "rgba(255,255,255,.52)", fontFamily: "DM Mono, monospace", fontSize: 21, letterSpacing: "0.1em"}}>A REAL CONVERSATION</div>
      <div style={{position: "absolute", left: 50, right: 50, top: 155, height: 370}}>
        <div style={{position: "absolute", left: 0, top: 15, fontSize: 25, color: "#65d8ff", fontWeight: 600}}>YOU</div>
        <div style={{position: "absolute", left: 0, top: 195, fontSize: 25, color: "#d9ff66", fontWeight: 600}}>BOT</div>
        <div style={{position: "absolute", left: 100, right: 0, top: 0, height: 140, borderRadius: 22, backgroundColor: "rgba(101,216,255,.07)", border: "1px solid rgba(101,216,255,.3)", overflow: "hidden"}}>
          <div style={{position: "absolute", left: 20, top: 15}}><Waveform frame={frame} color="#65d8ff" width={745} height={104} /></div>
        </div>
        <div style={{position: "absolute", left: 100, right: 0, top: 180, height: 140, borderRadius: 22, backgroundColor: "rgba(217,255,102,.06)", border: "1px solid rgba(217,255,102,.28)", overflow: "hidden"}}>
          <div style={{position: "absolute", left: 20, top: 15}}><Waveform frame={frame} color="#d9ff66" width={745} height={104} quiet={local < 68} offset={8} /></div>
        </div>
        <div style={{position: "absolute", left: cursor, top: -25, width: 2, height: 375, backgroundColor: "#f4b84a", boxShadow: "0 0 16px rgba(244,184,74,.7)"}} />
        <div style={{position: "absolute", left: 470, top: 118, padding: "11px 18px", borderRadius: 999, backgroundColor: "#d9ff66", color: "#101714", fontSize: 24, fontWeight: 700, opacity: interpolate(local, [58, 68, 102, 112], [0, 1, 1, 0], clamp)}}>mm-hm</div>
        <div style={{position: "absolute", left: 665, top: 300, padding: "11px 18px", borderRadius: 999, backgroundColor: "#ff765e", color: "#101714", fontSize: 23, fontWeight: 700, opacity: interpolate(local, [102, 112, 150, 160], [0, 1, 1, 0], clamp)}}>barge-in</div>
      </div>
      <div style={{position: "absolute", left: 50, right: 50, bottom: 64, display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 18}}>
        {[["BACKCHANNEL", "an ‘mm-hm’ while listening"], ["BARGE IN", "interrupt the bot mid sentence"], ["ENDPOINTING", "decide when speech is finished"]].map(([label, detail], index) => (
          <div key={label} style={{padding: "24px 26px", borderRadius: 20, border: "1px solid rgba(255,255,255,.16)", backgroundColor: "rgba(255,255,255,.025)", opacity: interpolate(local, [35 + index * 16, 50 + index * 16], [0, 1], clamp)}}>
            <div style={{fontFamily: "DM Mono, monospace", fontSize: 19, color: "#f4b84a"}}>{label}</div>
            <div style={{fontSize: 25, marginTop: 10, color: "rgba(255,255,255,.66)"}}>{detail}</div>
          </div>
        ))}
      </div>
    </div>
  );
};

const DuplexVisual: React.FC<{frame: number}> = ({frame}) => {
  const local = frame - 990;
  const frames = Array.from({length: 12});
  return (
    <div style={{position: "absolute", inset: 0}}>
      <div style={{position: "absolute", left: 50, top: 55, fontFamily: "DM Mono, monospace", fontSize: 21, color: "rgba(255,255,255,.52)", letterSpacing: "0.1em"}}>TWO STREAMS · ONE CLOCK</div>
      <div style={{position: "absolute", left: 50, right: 50, top: 145}}>
        <div style={{fontSize: 25, fontWeight: 700, color: "#65d8ff", marginBottom: 15}}>USER AUDIO</div>
        <div style={{height: 155, padding: "20px 28px", borderRadius: 24, border: "1px solid rgba(101,216,255,.4)", backgroundColor: "rgba(101,216,255,.07)"}}>
          <Waveform frame={frame} color="#65d8ff" width={805} height={112} />
        </div>
        <div style={{fontSize: 25, fontWeight: 700, color: "#d9ff66", marginTop: 38, marginBottom: 15}}>AGENT AUDIO</div>
        <div style={{height: 155, padding: "20px 28px", borderRadius: 24, border: "1px solid rgba(217,255,102,.4)", backgroundColor: "rgba(217,255,102,.06)"}}>
          <Waveform frame={frame} color="#d9ff66" width={805} height={112} offset={11} />
        </div>
      </div>
      <div style={{position: "absolute", left: 50, right: 50, bottom: 42, display: "flex", gap: 7}}>
        {frames.map((_, index) => {
          const live = (Math.floor(local / 5) % frames.length) === index;
          return (
            <div key={index} style={{height: 66, flex: 1, borderRadius: 13, border: `1px solid ${live ? "#65d8ff" : "rgba(255,255,255,.15)"}`, backgroundColor: live ? "rgba(101,216,255,.18)" : "rgba(255,255,255,.025)", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "DM Mono, monospace", fontSize: 18, color: live ? "#65d8ff" : "rgba(255,255,255,.38)"}}>{index * 80}<span style={{fontSize: 13, marginLeft: 2}}>ms</span></div>
          );
        })}
      </div>
    </div>
  );
};

const AsrBoundaryVisual: React.FC<{frame: number}> = ({frame}) => {
  const local = frame - 360;
  const secondVoice = interpolate(local, [48, 72], [0, 1], clamp);
  return (
    <div style={{position: "absolute", inset: 0, padding: "52px 50px"}}>
      <div style={{fontFamily: "DM Mono, monospace", fontSize: 21, color: "#f4b84a", letterSpacing: "0.08em"}}>ASR = AUTOMATIC SPEECH RECOGNITION</div>
      <div style={{fontSize: 28, color: "rgba(255,255,255,.6)", marginTop: 18}}>It converts audio into written words.</div>

      <div style={{marginTop: 45, padding: "28px 32px", borderRadius: 24, border: "1px solid rgba(255,255,255,.18)", backgroundColor: "rgba(255,255,255,.025)"}}>
        <div style={{fontFamily: "DM Mono, monospace", fontSize: 17, color: "rgba(255,255,255,.5)"}}>TRANSCRIPT</div>
        <div style={{fontFamily: "Instrument Serif, Georgia, serif", fontSize: 72, marginTop: 8}}>“I’m fine.”</div>
      </div>

      <div style={{marginTop: 22, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18}}>
        <div style={{padding: "24px 25px", minHeight: 205, borderRadius: 22, border: "1px solid rgba(101,216,255,.34)", backgroundColor: "rgba(101,216,255,.05)"}}>
          <div style={{fontFamily: "DM Mono, monospace", fontSize: 17, color: "#65d8ff"}}>STEADY · OPEN</div>
          <Waveform frame={frame * 0.45} color="#65d8ff" width={370} height={82} />
          <div style={{fontSize: 27, color: "rgba(255,255,255,.72)"}}>“I really am okay.”</div>
        </div>
        <div style={{padding: "24px 25px", minHeight: 205, borderRadius: 22, border: "1px solid rgba(255,118,94,.34)", backgroundColor: "rgba(255,118,94,.05)", opacity: secondVoice}}>
          <div style={{fontFamily: "DM Mono, monospace", fontSize: 17, color: "#ff765e"}}>LONG PAUSE · FLAT</div>
          <Waveform frame={frame * 0.28} color="#ff765e" width={370} height={82} quiet />
          <div style={{fontSize: 27, color: "rgba(255,255,255,.72)"}}>“Please notice I’m not.”</div>
        </div>
      </div>

      <div style={{position: "absolute", left: 50, right: 50, bottom: 45, padding: "22px 26px", borderRadius: 19, border: "1px solid rgba(244,184,74,.32)", backgroundColor: "rgba(244,184,74,.05)", display: "flex", alignItems: "center", justifyContent: "space-between"}}>
        <div><span style={{fontFamily: "DM Mono, monospace", color: "#f4b84a"}}>WER = 0%</span><span style={{color: "rgba(255,255,255,.5)"}}> · word error rate</span></div>
        <div style={{fontSize: 27, color: "#f4b84a"}}>Human meaning can still be missed.</div>
      </div>
    </div>
  );
};

const TtsBoundaryVisual: React.FC<{frame: number}> = ({frame}) => {
  const local = frame - 570;
  const secondDelivery = interpolate(local, [50, 74], [0, 1], clamp);
  return (
    <div style={{position: "absolute", inset: 0, padding: "52px 50px"}}>
      <div style={{fontFamily: "DM Mono, monospace", fontSize: 21, color: "#b89cff", letterSpacing: "0.08em"}}>TTS = TEXT TO SPEECH</div>
      <div style={{fontSize: 28, color: "rgba(255,255,255,.6)", marginTop: 18}}>It gives the model’s written answer a voice.</div>

      <div style={{marginTop: 48, padding: "25px 30px", borderRadius: 22, border: "1px solid rgba(255,255,255,.16)", backgroundColor: "rgba(255,255,255,.025)"}}>
        <div style={{fontFamily: "DM Mono, monospace", fontSize: 17, color: "rgba(255,255,255,.48)"}}>THE TEXT IS IDENTICAL</div>
        <div style={{marginTop: 8, fontFamily: "Instrument Serif, Georgia, serif", fontSize: 66}}>“I understand.”</div>
      </div>

      <div style={{marginTop: 22, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18}}>
        <div style={{padding: "24px 25px", borderRadius: 22, border: "1px solid rgba(255,118,94,.34)", backgroundColor: "rgba(255,118,94,.05)"}}>
          <div style={{fontFamily: "DM Mono, monospace", fontSize: 17, color: "#ff765e"}}>FAST · BRIGHT · IMMEDIATE</div>
          <Waveform frame={frame * 0.7} color="#ff765e" width={370} height={74} />
          <div style={{fontSize: 27}}>It can sound like closure.</div>
        </div>
        <div style={{padding: "24px 25px", borderRadius: 22, border: "1px solid rgba(184,156,255,.38)", backgroundColor: "rgba(184,156,255,.06)", opacity: secondDelivery}}>
          <div style={{fontFamily: "DM Mono, monospace", fontSize: 17, color: "#b89cff"}}>SOFT · SLOW · SPACE FIRST</div>
          <Waveform frame={frame * 0.32} color="#b89cff" width={370} height={74} />
          <div style={{fontSize: 27}}>It can sound like presence.</div>
        </div>
      </div>

      <div style={{position: "absolute", left: 50, right: 50, bottom: 48, padding: "24px 28px", borderRadius: 20, border: "1px solid rgba(184,156,255,.32)", backgroundColor: "rgba(184,156,255,.05)", fontSize: 26, lineHeight: 1.25}}>Sometimes the most human response is a pause,<br /><span style={{color: "#b89cff"}}>a quiet “mm-hm”, or one careful question.</span></div>
    </div>
  );
};

const GptLiveVisual: React.FC<{frame: number}> = ({frame}) => {
  const local = frame - 1200;
  const pulse = interpolate(local % 32, [0, 16, 32], [0.35, 1, 0.35], clamp);
  return (
    <div style={{position: "absolute", inset: 0}}>
      <div style={{position: "absolute", left: 50, top: 52, fontFamily: "DM Mono, monospace", fontSize: 21, color: "rgba(255,255,255,.52)", letterSpacing: "0.1em"}}>ONE EXAMPLE: GPT-LIVE</div>

      <div style={{position: "absolute", left: 54, top: 145, width: 355, height: 355, borderRadius: 200, border: "2px solid #65d8ff", backgroundColor: "rgba(101,216,255,.075)", boxShadow: `0 0 ${34 + pulse * 28}px rgba(101,216,255,.22)`, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center"}}>
        <div style={{fontFamily: "DM Mono, monospace", fontSize: 19, color: "#65d8ff", letterSpacing: "0.08em"}}>CONTINUOUS INTERACTION</div>
        <div style={{fontFamily: "Instrument Serif, Georgia, serif", fontSize: 72, marginTop: 13}}>GPT-Live</div>
        <div style={{fontSize: 23, lineHeight: 1.28, color: "rgba(255,255,255,.66)", marginTop: 14}}>listen · speak · pause<br />interrupt · invoke tools</div>
      </div>

      <div style={{position: "absolute", left: 440, top: 302, width: 95, height: 3, backgroundColor: "rgba(255,255,255,.2)"}}>
        <div style={{height: "100%", width: `${interpolate(local % 28, [0, 28], [0, 100], clamp)}%`, backgroundColor: "#f4b84a"}} />
      </div>
      <div style={{position: "absolute", left: 448, top: 264, fontFamily: "DM Mono, monospace", fontSize: 16, color: "#f4b84a"}}>DELEGATE</div>

      <div style={{position: "absolute", right: 54, top: 176, width: 390, height: 280, borderRadius: 30, border: "2px solid #f4b84a", backgroundColor: "rgba(244,184,74,.07)", padding: "39px 42px"}}>
        <div style={{fontFamily: "DM Mono, monospace", fontSize: 19, color: "#f4b84a", letterSpacing: "0.08em"}}>BACKGROUND FRONTIER BRAIN</div>
        <div style={{fontFamily: "Instrument Serif, Georgia, serif", fontSize: 72, marginTop: 20}}>GPT-5.5</div>
        <div style={{fontSize: 25, lineHeight: 1.28, color: "rgba(255,255,255,.66)", marginTop: 13}}>search · reason<br />complex agentic work</div>
      </div>

      <div style={{position: "absolute", left: 50, right: 50, bottom: 54, display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 18}}>
        <div style={{padding: "25px 26px", borderRadius: 22, border: "1px solid rgba(101,216,255,.35)", backgroundColor: "rgba(101,216,255,.055)"}}>
          <div style={{fontFamily: "DM Mono, monospace", fontSize: 18, color: "#65d8ff"}}>CONTINUOUS VOICE</div>
          <div style={{fontSize: 25, lineHeight: 1.2, marginTop: 10}}>listen and speak<br />together</div>
        </div>
        <div style={{padding: "25px 26px", borderRadius: 22, border: "1px solid rgba(255,118,94,.35)", backgroundColor: "rgba(255,118,94,.055)"}}>
          <div style={{fontFamily: "DM Mono, monospace", fontSize: 18, color: "#ff765e"}}>DEEPER WORK</div>
          <div style={{fontSize: 25, lineHeight: 1.2, marginTop: 10}}>search and reason<br />in the background</div>
        </div>
        <div style={{padding: "25px 26px", borderRadius: 22, border: "1px solid rgba(217,255,102,.35)", backgroundColor: "rgba(217,255,102,.05)"}}>
          <div style={{fontFamily: "DM Mono, monospace", fontSize: 18, color: "#d9ff66"}}>THE NEW SPLIT</div>
          <div style={{fontSize: 25, lineHeight: 1.2, marginTop: 10}}>fast interaction<br />slow cognition</div>
        </div>
      </div>
    </div>
  );
};

const BuildHintVisual: React.FC<{frame: number}> = ({frame}) => {
  const local = frame - 1440;
  const goals = [
    {label: "TIMING", text: "respond without waiting for a clean turn", color: "#65d8ff"},
    {label: "MEANING", text: "preserve names, numbers, intent and tone", color: "#f4b84a"},
    {label: "CONTROL", text: "know what was heard before taking action", color: "#d9ff66"},
  ];
  return (
    <div style={{position: "absolute", inset: 0, padding: "62px 58px"}}>
      <div style={{fontFamily: "Instrument Serif, Georgia, serif", fontSize: 82, lineHeight: 0.98, maxWidth: 790}}>The next voice stack has to solve all three.</div>
      <div style={{marginTop: 56, display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 18}}>
        {goals.map((goal, index) => (
          <div key={goal.label} style={{minHeight: 270, padding: "27px 25px", borderRadius: 24, border: `1px solid ${goal.color}55`, backgroundColor: `${goal.color}0d`, opacity: interpolate(local, [22 + index * 18, 42 + index * 18], [0, 1], clamp)}}>
            <div style={{fontFamily: "DM Mono, monospace", fontSize: 18, letterSpacing: "0.08em", color: goal.color}}>{goal.label}</div>
            <div style={{fontSize: 30, lineHeight: 1.22, marginTop: 24}}>{goal.text}</div>
          </div>
        ))}
      </div>
      <div style={{position: "absolute", left: 58, bottom: 58, fontSize: 28, color: "rgba(255,255,255,.58)"}}>I am building a project around this architecture. More soon.</div>
    </div>
  );
};

export const VoiceAiIntro: React.FC = () => {
  const frame = useCurrentFrame();
  const slowFrame = frame;
  const accent = interpolateColors(
    slowFrame,
    [0, 170, 190, 350, 370, 560, 580, 770, 790, 980, 1000, 1190, 1210, 1430, 1450, 1679],
    ["#d9ff66", "#d9ff66", "#ff765e", "#ff765e", "#f4b84a", "#f4b84a", "#b89cff", "#b89cff", "#f4b84a", "#f4b84a", "#65d8ff", "#65d8ff", "#65d8ff", "#65d8ff", "#d9ff66", "#d9ff66"],
  );

  return (
    <AbsoluteFill style={{backgroundColor: "#0c1311", color: "#f5f1e7", fontFamily: "DM Sans, sans-serif", overflow: "hidden"}}>
      <Interactive.Div name="Ambient color" style={{position: "absolute", inset: -250, background: `radial-gradient(circle at 12% 14%, ${accent}38 0%, ${accent}10 28%, transparent 55%)`}} />
      <Interactive.Div name="Fine grain" style={{position: "absolute", inset: 0, opacity: 0.105, backgroundImage: "radial-gradient(rgba(255,255,255,.55) .65px, transparent .75px)", backgroundSize: "5px 5px"}} />

      <div style={{position: "absolute", left: 74, top: 118, width: 720, height: 850}}>
        {phases.map((phase, index) => (
          <div key={phase.label} style={{opacity: phaseOpacity(slowFrame, phase.start, phase.end)}}>
            <Interactive.Div name={`Phase ${index + 1} label`} style={{position: "absolute", top: 0, left: 0, color: phase.accent, fontFamily: "DM Mono, monospace", fontSize: 23, letterSpacing: "0.11em"}}>{phase.label}</Interactive.Div>
            <Interactive.Div name={`Phase ${index + 1} headline`} style={{position: "absolute", top: 68, left: 0, width: 720, fontFamily: "Instrument Serif, Georgia, serif", fontSize: index === 7 ? 78 : 86, lineHeight: 0.98, letterSpacing: "-0.045em", color: "#f5f1e7"}}>
              {phase.lines.map((line) => <div key={line}>{line}</div>)}
            </Interactive.Div>
            <Interactive.Div name={`Phase ${index + 1} explanation`} style={{position: "absolute", top: 420, left: 0, width: 700, paddingLeft: 28, borderLeft: `5px solid ${phase.accent}`, fontSize: 38, lineHeight: 1.22, fontWeight: 600, color: "rgba(255,255,255,.84)"}}>
              {phase.body.map((line) => <div key={line}>{line}</div>)}
            </Interactive.Div>
          </div>
        ))}
      </div>

      <Interactive.Div name="Visual laboratory" style={{position: "absolute", left: 835, top: 127, width: 1010, height: 824, borderRadius: 30, border: "1px solid rgba(255,255,255,.22)", backgroundColor: "rgba(4,8,7,.52)", overflow: "hidden"}}>
        <div style={{opacity: phaseOpacity(slowFrame, 0, 180)}}><PipelineVisual frame={slowFrame} /></div>
        <div style={{opacity: phaseOpacity(slowFrame, 180, 360)}}><CascadeTimingVisual frame={slowFrame} /></div>
        <div style={{opacity: phaseOpacity(slowFrame, 360, 570)}}><AsrBoundaryVisual frame={slowFrame} /></div>
        <div style={{opacity: phaseOpacity(slowFrame, 570, 780)}}><TtsBoundaryVisual frame={slowFrame} /></div>
        <div style={{opacity: phaseOpacity(slowFrame, 780, 990)}}><SocialTimingVisual frame={slowFrame} /></div>
        <div style={{opacity: phaseOpacity(slowFrame, 990, 1200)}}><DuplexVisual frame={slowFrame} /></div>
        <div style={{opacity: phaseOpacity(slowFrame, 1200, 1440)}}><GptLiveVisual frame={slowFrame} /></div>
        <div style={{opacity: phaseOpacity(slowFrame, 1440, 1680)}}><BuildHintVisual frame={slowFrame} /></div>
      </Interactive.Div>

      <Interactive.Div name="Progress" style={{position: "absolute", left: 74, right: 74, bottom: 45, height: 2, backgroundColor: "rgba(255,255,255,.13)"}}>
        <div style={{height: "100%", width: `${interpolate(slowFrame, [0, 1679], [0, 100], clamp)}%`, backgroundColor: accent}} />
      </Interactive.Div>
    </AbsoluteFill>
  );
};
