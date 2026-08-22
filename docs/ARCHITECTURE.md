# Duet / Aira architecture

Duet is a guarded, speculative, controlled-duplex voice-agent system. Its product is **Aira**, a
disclosed real-estate sales concierge for ASBL Broadway. It is not one monolithic speech model:
streaming ASR, turn management, deterministic policy, semantic planning, actions, TTS and telemetry
are independent lanes joined by events, generation IDs and cancellation rules.

> **Diagram legend:** solid boxes describe the running localhost implementation. Dashed boxes and
> edges describe the production target. The current demo is instrumented but remains single-session
> and is not authorized for public outbound calling.

## 1. System context

~~~mermaid
flowchart LR
    Caller["Caller<br/>voice + interruptions"]
    Operator["ASBL operator<br/>facts, policy, escalation"]
    Browser["Browser client<br/>AudioWorklet + AEC"]
    Duet["Duet / Aira<br/>conversation runtime"]
    Sarvam["Sarvam<br/>Saaras ASR + Bulbul TTS"]
    Gemini["Gemini Flash Lite<br/>semantic planner"]
    Facts[("Versioned ASBL<br/>fact registry")]
    Actions["ASBL action gateway<br/>or local idempotent ledger"]
    Obs["Self-hosted observability<br/>Langfuse + Prometheus + Loki + Postgres"]
    Telephony["Future telephony adapter<br/>SIP / Exotel / Twilio / Plivo"]

    Caller <--> Browser
    Browser <-->|"24 kHz PCM + JSON events<br/>WebSocket"| Duet
    Duet <-->|"streaming audio / text"| Sarvam
    Duet <-->|"bounded prompt / structured plan"| Gemini
    Facts -->|"allowlisted evidence"| Duet
    Duet <-->|"idempotent action contract"| Actions
    Duet -.->|"bounded async telemetry"| Obs
    Operator --> Facts
    Operator <-->|"human handoff + outcomes"| Actions
    Telephony -.->|"future transport adapter"| Duet

    classDef core fill:#18324a,stroke:#58a6ff,color:#fff,stroke-width:2px;
    classDef external fill:#27212f,stroke:#bc8cff,color:#fff;
    classDef data fill:#17352d,stroke:#56d364,color:#fff;
    classDef future fill:#222,stroke:#8b949e,color:#c9d1d9,stroke-dasharray: 5 5;
    class Duet core;
    class Sarvam,Gemini external;
    class Facts,Actions,Obs data;
    class Telephony future;
~~~

The product boundary is deliberate:

- Duet owns timing, policy, state, evidence, cancellation and measurement.
- Sarvam owns hosted recognition and synthesis in the default demo.
- Gemini proposes structured next responses. It does not own consent, opt-out, source truth,
  action truth, playback or interruption policy.
- ASBL systems remain authoritative for volatile inventory, final price, offers and completed actions.

## 2. Concurrent runtime lanes

The runtime overlaps work wherever causality allows it. Concurrency cannot remove two gates: enough
stable caller intent must exist before committing an answer, and enough verified response content
must exist before allowing speech.

~~~mermaid
flowchart TB
    subgraph Transport["Transport lane — continuous"]
        Mic["Browser microphone<br/>24 kHz mono"]
        WSIn["WebSocket ingress<br/>bounded queues"]
        Playback["AudioWorklet playback<br/>adaptive jitter buffer"]
        Mic --> WSIn
    end

    subgraph Listen["Listen lane — continuous"]
        Stream["Sarvam realtime socket"]
        VAD["speech-start / speech-end"]
        Partial["partial transcript"]
        Final["final transcript"]
        WSIn --> Stream
        Stream --> VAD
        Stream --> Partial
        Stream --> Final
    end

    subgraph Turn["Turn lane — streaming"]
        Assemble["TurnAssembler<br/>merge + grace window"]
        Speculate["stable-partial speculation"]
        Commit{"final preserves<br/>partial meaning?"}
        Partial --> Assemble --> Speculate
        Final --> Commit
        Speculate --> Commit
    end

    subgraph Control["Deterministic control lane — authoritative"]
        Consent["AI disclosure + permission"]
        Interrupt["echo-aware barge-in"]
        Repair["pause / clarify / new intent / opt-out"]
        Safety["fact, repetition, sensitive-trait<br/>and capability guards"]
        Generation["generation IDs<br/>stale-result suppression"]
        VAD --> Interrupt --> Repair --> Generation
        Consent --> Safety
    end

    subgraph Intelligence["Semantic lane — asynchronous"]
        Context["bounded conversation history"]
        Planner["Gemini structured planner"]
        Guidance["Guidance<br/>speech + evidence + actions"]
        Context --> Planner --> Guidance
        Commit -->|"commit or replace"| Planner
    end

    subgraph Egress["Speech and action lanes"]
        Gate{"speech safety gate"}
        TTS["persistent Sarvam TTS"]
        Pace["absolute-clock pacing"]
        Action["ActionLayer<br/>idempotent async request"]
        Guidance --> Gate --> TTS --> Pace --> Playback
        Guidance --> Action
        Interrupt -->|"cancel generation"| TTS
        Interrupt -->|"flush queues"| Playback
        Safety --> Gate
        Generation --> Gate
    end

    Events["LiveSessionTelemetry<br/>non-blocking fan-out"]
    WSIn -.-> Events
    Assemble -.-> Events
    Planner -.-> Events
    Gate -.-> Events
    TTS -.-> Events
    Action -.-> Events
~~~

### Runtime invariants

1. The microphone remains armed during TTS only in controlled-barge-in mode.
2. Speech-start yields the acoustic floor; transcript semantics decide the conversational response.
3. Speculative reasoning may run early, but cannot speak before final semantic commit.
4. An older request or speech generation cannot regain authority after a newer caller turn.
5. Policy and action truth remain deterministic, outside the LLM.
6. Telemetry may be dropped under pressure; caller audio may not be delayed by telemetry.

## 3. Normal-turn sequence

~~~mermaid
sequenceDiagram
    autonumber
    actor U as Caller
    participant B as Browser
    participant S as Session
    participant A as Sarvam ASR
    participant T as Turn manager
    participant G as Gemini planner
    participant P as Policy gate
    participant V as Sarvam TTS

    U->>B: Speaks
    B->>S: Continuous PCM
    S->>A: Stream audio
    A-->>S: speech-start + partials
    S->>T: Update candidate turn
    T-->>G: Stable partial (speculative)
    Note over G: Work starts early;<br/>speech is quarantined
    A-->>S: speech-end + final transcript
    S->>T: Commit final turn
    alt Partial meaning preserved
        T-->>G: Commit speculative request ID
    else Meaning changed
        T-->>G: Suppress old ID; request replacement
    end
    G-->>S: Streamed speech field + structured guidance
    S->>P: Consent, source, capability, repetition and staleness checks
    alt Passed and current
        P->>V: Approved short utterance
        V-->>S: Streaming PCM
        S-->>B: Clock-paced audio
        B-->>U: Audible response
    else Rejected or stale
        P-->>S: Suppress and emit auditable reason
    end
~~~

The latest localhost smoke measured roughly 2.06 seconds from final speech end to first server
audio. This is optimization evidence, not a claim of 300 ms response latency.

## 4. Barge-in and interruption repair

~~~mermaid
sequenceDiagram
    autonumber
    actor U as Caller
    participant B as Browser
    participant S as Session
    participant A as Sarvam ASR
    participant V as TTS stream
    participant G as Gemini

    V-->>B: Aira is speaking
    B-->>U: Playback
    U->>B: Interrupts
    B->>S: PCM remains live
    S->>A: Streaming audio
    A-->>S: speech-start
    par Cancel playback ownership
        S->>V: Close current generation
        S->>S: Clear speech and PCM queues
        S-->>B: playback_cancel
        B->>B: Flush jitter buffer
    and Continue understanding
        A-->>S: Partial then final transcript
    end
    S->>S: Classify interruption semantics
    alt Explicit opt-out
        S-->>B: Acknowledge and latch DNC
    else Pause request
        S-->>B: Brief pause acknowledgement
    else Genuine ambiguity
        S-->>B: One clarification; at most one focused reprompt
    else Explicit preference or question
        S->>G: New turn supersedes stale reasoning
        G-->>S: Grounded replacement
        S-->>B: New streamed speech
    end
~~~

The cancellation fast lane is independent of Gemini. The latest real-provider smoke yielded
playback in 233 ms; semantic repair happens afterward.

~~~mermaid
stateDiagram-v2
    [*] --> Listening
    Listening --> Speaking: safe current response
    Speaking --> Yielding: verified speech-start
    Yielding --> OptedOut: explicit stop / DNC
    Yielding --> Paused: wait / hold on
    Yielding --> Clarifying: vague change
    Yielding --> Reasoning: explicit question / preference
    Clarifying --> Reasoning: meaningful answer
    Clarifying --> Clarifying: first unclear answer / focused reprompt
    Clarifying --> WaitingForCaller: later fragment / no repeated speech
    WaitingForCaller --> Reasoning: meaningful answer
    Paused --> Listening: caller resumes
    Reasoning --> Speaking: current response passes guards
    Reasoning --> Listening: wait or rejected response
    Speaking --> Listening: playback completes
    OptedOut --> [*]
~~~

## 5. Generation ownership

~~~mermaid
flowchart LR
    P1["partial turn<br/>request 17"] --> R1["speculative result 17"]
    F{"final transcript"}
    F -->|"semantic match"| C1["commit 17"]
    F -->|"meaning changed"| N["request 18"]
    R1 --> C1
    R1 -.->|"uncommitted"| Drop1["quarantine / drop"]
    N --> R2["result 18"]
    C1 --> Current{"latest request?"}
    R2 --> Current
    Current -->|"yes"| Guard["speech + action guards"]
    Current -->|"no"| Drop2["stale response suppressed"]
    Guard --> Speak["speech generation ID"]
    Barge["barge-in"] -->|"invalidate"| Speak
    Barge -->|"clear buffers"| Drop2
~~~

Cancellation has three domains:

- **Reasoning:** old results lose authority even if a provider request cannot be physically stopped.
- **Speech:** the active TTS generator closes and unread provider audio is discarded.
- **Playback:** server queues and the browser jitter buffer are flushed.

## 6. Grounding and action consistency

~~~mermaid
flowchart TB
    CallerText["Accepted caller transcript"]
    StaticFacts[("Versioned fact registry<br/>claim + source + freshness")]
    Volatile[("ASBL authenticated systems<br/>price, inventory, offers")]
    Prompt["Bounded planner prompt"]
    Plan["Structured Guidance"]
    ClaimGate{"Factual claims have<br/>allowlisted sources?"}
    ActionGate{"Action is allowlisted<br/>and configured?"}
    Ledger[("Idempotent action ledger")]
    Gateway["Authenticated ASBL gateway"]
    Speech["Approved speech"]
    Block["Suppress or factual boundary"]

    CallerText --> Prompt
    StaticFacts --> Prompt
    Prompt --> Plan --> ClaimGate
    ClaimGate -->|"yes"| Speech
    ClaimGate -->|"no"| Block
    Volatile -.->|"future lookup"| ClaimGate
    Plan --> ActionGate
    ActionGate -->|"local demo"| Ledger
    ActionGate -.->|"production"| Gateway
    Ledger -->|"accepted receipt only"| Speech
    Gateway -->|"accepted / completed / failed"| Speech
~~~

An LLM may request an action but cannot declare it complete. The adapter response is the only
authority for “sent,” “scheduled,” “updated” or “completed.”

## 7. Data and trust boundaries

~~~mermaid
flowchart LR
    subgraph Device["Caller device"]
        Raw["Raw microphone audio"]
        AEC["Browser AEC / noise suppression"]
    end
    subgraph Host["Duet trusted application boundary"]
        State["Ephemeral session state"]
        Policy["Deterministic policy"]
        Redact["Telemetry redaction<br/>hash + length by default"]
        Capture[("Opt-in local eval capture")]
    end
    subgraph Providers["External processors"]
        STT["Sarvam ASR"]
        LLM["Gemini"]
        TTS["Sarvam TTS"]
    end
    subgraph Durable["Self-hosted durable systems"]
        PG[("Postgres call summary")]
        LF["Langfuse trace"]
        Loki["Loki logs"]
        Objects[("Recording storage target")]
    end

    Raw --> AEC --> State
    State -->|"audio"| STT
    State -->|"bounded transcript + facts"| LLM
    State -->|"approved text"| TTS
    State --> Redact
    Redact --> PG
    Redact --> LF
    Redact --> Loki
    State -->|"explicit capture consent"| Capture
    Capture -.->|"production retention policy"| Objects
~~~

Default telemetry excludes raw transcript, prompt and response content. Local ASR capture is a
separate explicit choice. Production recording still needs durable consent, retention and deletion.

## 8. Observability

~~~mermaid
flowchart LR
    Session["LiveSessionTelemetry<br/>session_id + trace_id"]
    Queue["Bounded async exporters"]
    Metrics["/metrics"]
    Json["JSONL event log"]
    Summary["Call summary"]
    Langfuse["Langfuse"]
    Prom["Prometheus"]
    Alloy["Grafana Alloy"]
    Loki["Loki"]
    PG["Postgres"]
    Grafana["Grafana"]

    Session --> Queue -->|"fail-silent"| Langfuse
    Session --> Metrics --> Prom
    Queue --> Json --> Alloy --> Loki
    Session --> Summary --> PG
    Prom --> Grafana
    Loki --> Grafana
    PG --> Grafana
~~~

Every backend shares a session and trace ID. Export queues are bounded; an observability outage
increments a drop metric instead of taking ownership of the audio clock.

| Layer | Primary signals |
|---|---|
| Transport | active sessions, queue pressure, dropped frames, disconnect reason |
| ASR / turn | speech events, accepted turns, endpoint latency, speculation replacement |
| Reasoning | provider latency, tokens, errors, stale suppression, cost |
| Speech | first-audio latency, underruns, interrupted/completed utterances |
| Interaction | yield latency, clarification repair, overlap, takeover rate |
| Actions | requested, accepted, completed, failed, idempotency outcomes |
| Business | explicit qualification evidence—not purchase probability |

## 9. Current deployment

~~~mermaid
flowchart TB
    Browser["localhost:8990<br/>browser UI"]
    Server["aiohttp process<br/>single active Session"]
    APIs["Sarvam + Gemini APIs"]
    Local["local capture, action and JSONL files"]
    LF["Langfuse :3000"]
    Prom["Prometheus :9099"]
    Loki["Loki :3100"]
    PG["Postgres :5433"]
    Graf["Grafana :3001"]

    Browser <-->|"ws:// PCM + events"| Server
    Server <--> APIs
    Server --> Local
    Server --> LF
    Server --> Prom
    Server --> PG
    Local --> Loki
    LF --> Graf
    Prom --> Graf
    Loki --> Graf
    PG --> Graf
~~~

The largest blocker is not only model quality: the server exposes one process-global active session
and lacks authenticated public transport, distributed ownership and restart recovery.

## 10. Production target

~~~mermaid
flowchart TB
    subgraph Edge["Edge / media plane"]
        Caddy["Caddy<br/>TLS + WSS"]
        Browser2["Browser / WebRTC"]
        PSTN["PSTN / SIP provider"]
        Adapter["Transport adapters<br/>browser, SIP, PSTN"]
        Browser2 --> Caddy --> Adapter
        PSTN --> Adapter
    end

    subgraph Runtime["Stateless application replicas"]
        Admission["Admission control<br/>auth + rate + cost limits"]
        Supervisor["SessionSupervisor<br/>isolated scope per call"]
        Ingress["Audio ingress"]
        Turns["Turn manager"]
        Engine["Conversation engine"]
        Egress["Speech egress"]
        Admission --> Supervisor
        Supervisor --> Ingress
        Supervisor --> Turns
        Supervisor --> Engine
        Supervisor --> Egress
    end

    subgraph StatePlane["Durable state plane"]
        Lease[("Session lease / presence")]
        Postgres[("Consent, DNC, call and action audit")]
        Objects[("MinIO or volume recordings")]
    end

    subgraph Providers["Replaceable adapters"]
        ASR["ASR primary + fallback"]
        Brain["Reasoning primary + fallback"]
        Voice["TTS primary + fallback"]
        CRM["ASBL action gateway"]
    end

    subgraph Operations["Operations plane"]
        OTel["correlated telemetry"]
        Dash["Grafana + Langfuse"]
        Alert["SLO alerts + runbooks"]
    end

    Adapter --> Admission
    Supervisor <--> Lease
    Supervisor --> Postgres
    Supervisor --> Objects
    Ingress <--> ASR
    Engine <--> Brain
    Egress <--> Voice
    Engine <--> CRM
    Supervisor -.-> OTel --> Dash --> Alert
~~~

~~~mermaid
classDiagram
    class SessionSupervisor {
      +session_id
      +trace_id
      +deadline
      +start()
      +cancel(reason)
      +finish(reason)
    }
    class TransportAdapter {
      <<interface>>
      +receive_audio()
      +send_audio()
      +clear_playback()
      +close()
    }
    class TurnManager {
      +on_speech_event()
      +on_partial()
      +commit_final()
    }
    class ConversationEngine {
      +handle_turn()
      +apply_policy()
      +request_action()
    }
    class SpeechEgress {
      +speak(generation)
      +cancel(generation)
    }
    class TelemetryPort {
      <<interface>>
      +event()
      +observe_latency()
      +finish()
    }
    SessionSupervisor *-- TransportAdapter
    SessionSupervisor *-- TurnManager
    SessionSupervisor *-- ConversationEngine
    SessionSupervisor *-- SpeechEgress
    SessionSupervisor o-- TelemetryPort
~~~

Graphify found the current Session class to be the largest coupling hub. Migration uses a strangler:

1. preserve the WebSocket contract and cancellation tests;
2. extract SessionSupervisor and per-call lifecycle;
3. extract transport-neutral audio ingress and speech egress;
4. move turn and interruption state behind explicit commands;
5. isolate providers with deadlines, circuit breakers and fallbacks;
6. add multi-session load, disconnect, restart and chaos tests;
7. add telephony only after browser behavior meets the same interaction SLOs.

## 11. Failure containment

| Failure | Required behavior | Current state |
|---|---|---|
| ASR disconnect | reconnect once, preserve boundary, then fall back or close clearly | Bounded reconnect and local fallback; continuity needs more testing |
| Gemini slow/unavailable | timeout, suppress stale result, avoid fabrication | Timeout and fail-silent path; conversational fallback is incomplete |
| TTS failure | stop generation, clear playback, preserve understandable state | Error surfaced and generator discarded; no automatic fallback |
| Caller interrupts | yield immediately, understand final turn, repair coherently | Implemented and regression-tested |
| Action retry | idempotency key prevents duplicate customer action | Local and remote contracts support idempotent IDs |
| Telemetry outage | never delay audio; expose dropped telemetry | Implemented with bounded exporters |
| Process restart | restore consent/DNC or terminate safely | Not implemented |
| Load spike | reject new sessions before active-call latency collapses | Not implemented |

## 12. Architectural SLOs

These are targets, not current claims:

| Signal | Target |
|---|---:|
| Caller audio start → playback cancelled, p95 | ≤300 ms |
| Final speech end → first audible response, p50 | ≤700 ms |
| Final speech end → first audible response, p95 | ≤1,200 ms |
| Stale response spoken after superseding turn | 0 |
| Opt-out acknowledgement and DNC latch | 100% |
| Unsupported factual or completed-action claim | 0 |
| Telemetry-induced audio delay | 0 ms by design |
| Session isolation at supported concurrency | 100% |

Latency counts only if WER, task success, grounding, overlap and naturalness do not regress. See the
[evaluation contract](../eval/README.md).

## 13. Code map

| Concern | Current implementation |
|---|---|
| Browser transport and session orchestration | web-demo/server.py, browser UI and AudioWorklet |
| ASR and speech detection | agent/duet_agent/asr.py and Sarvam realtime loop |
| Turn assembly and semantic commit | agent/duet_agent/turns.py and session speculation controls |
| Persona, facts and deterministic policy | agent/duet_agent/persona.py |
| Semantic planning | agent/duet_agent/reasoning.py |
| Actions and idempotency | agent/duet_agent/actions.py |
| TTS adapters and cancellation | agent/duet_agent/tts.py |
| Live telemetry | agent/duet_agent/live_telemetry.py and telemetry.py |
| Interaction, reasoning, ASR and TTS evaluation | eval/ |
| Self-hosted operations stack | infra/ |

## 14. Explicit non-goals

- Duet does not train or claim to own Sarvam, Gemini, Moshi or PersonaPlex.
- It exposes decision summaries, evidence and timings—not private chain-of-thought.
- It does not infer protected traits, personality or purchase probability.
- It does not promise appreciation, rental yield, inventory, discounts or legal outcomes.
- It does not claim native full duplex; the default is a controlled-duplex streaming cascade.
- Personal-learning and tutoring products are outside this repository. They may consume a future
  public Duet session contract without coupling their domain model or storage to Duet.

## 15. Related documents

- [Production readiness](PRODUCTION_READINESS.md)
- [Research direction](RESEARCH_DIRECTION.md)
- [Evaluation contract](../eval/README.md)
- [ASBL product behavior](ASBL_VOICE_AGENT.md)
- [Decisions journal](DECISIONS.md)
- [Two-day learning path](LEARNING_IN_2_DAYS.md)
