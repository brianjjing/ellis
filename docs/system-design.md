# Ellis system design

Ellis is one FastAPI service, deployed as a single Docker container on a Vultr server with Coolify, that also serves
the React app. The applicant talks through Cartesia; Claude runs the conversation through tools that call our own
case logic; four Creao agents work the case in the background; the clinic reviews before the applicant signs.
Ellis never files and never gives legal advice.

## 1. Architecture

```mermaid
flowchart LR
  subgraph Browser["Browser · React + Vite + TypeScript"]
    APP["Applicant app<br/>chat, form, review"]
    CLIN["Clinic workspace<br/>cases, review queue"]
    MIC["VoiceClient<br/>mic worklet + level gate"]
  end

  subgraph Host["Vultr server · Coolify · one container"]
    API["FastAPI Case API<br/>serves the web app too"]
    VS["VoiceSession<br/>WS /api/a/voice"]
    LIA["LlmLiaison<br/>Claude conversation"]
    CS["case_service<br/>facts, flags, gate, state"]
    RULES["rules engine<br/>dates, presence, fees"]
    BUS["event bus"]
    RUN["agent runner<br/>debounce, retries"]
    EXT["extraction worker<br/>sandboxed subprocess"]
    PKT["packet builder<br/>N-400 PDF + packet"]
  end

  subgraph Ext["Outside services"]
    INK["Cartesia Ink-2 / ink-whisper<br/>speech to text"]
    SONIC["Cartesia Sonic 3.6<br/>text to speech"]
    CLAUDE["Claude<br/>Messages API"]
    CREAO["Creao<br/>4 agent apps"]
  end

  DB[("Supabase Postgres<br/>append-only events")]
  FILES[("Supabase Storage<br/>uploads, packets")]

  MIC -- "PCM16 16 kHz up · lines + audio down" --> VS
  APP -- "REST /api/a/*" --> API
  CLIN -- "REST /api/clinic/*" --> API
  BUS -- "WS /api/a/stream and /api/clinic/stream" --> APP
  BUS --> CLIN
  VS -- "audio frames" --> INK
  INK -- "live transcript" --> VS
  VS -- "speak line" --> SONIC
  SONIC -- "audio + word timestamps" --> VS
  VS --> LIA
  LIA -- "turn + live case data + tools" --> CLAUDE
  LIA -- "record_fact, read_back, flags" --> CS
  API --> CS
  CS --> RULES
  CS -- "SQL" --> DB
  CS -- "emit event" --> BUS
  BUS -- "events" --> RUN
  RUN -- "case bundle · poll runs" --> CREAO
  RUN -- "validated proposals" --> CS
  API -- "uploads" --> FILES
  API --> EXT
  EXT -- "extracted fields" --> CS
  CS --> PKT
  PKT --> FILES
```

| Layer | Technology | Code |
|---|---|---|
| Hosting | Docker on Vultr, deployed by Coolify (HTTPS, redeploy on push to `main`) | `Dockerfile` |
| Web app | React, Vite, TypeScript, served by the API from the same origin | `frontend/src` |
| API | FastAPI on Python 3.12, one process | `backend/ellis/api` |
| Data | Postgres and private file storage on Supabase; Alembic migrations | `backend/ellis/db.py`, `services/storage.py` |
| Voice | Cartesia Ink-2 (en, es, fr, hi, ja) or ink-whisper (other languages), Sonic 3.6 in 44 languages | `backend/ellis/voice/cartesia.py` |
| Conversation | Claude with tools; fixed legal lines in `scripts_<lang>.yaml` | `voice/llm_liaison.py`, `prompts/liaison.md` |
| Staff agents | Four Creao apps behind one typed proposal format | `backend/ellis/agents` |
| Rules | Pure, versioned rules for dates, physical presence and fees | `backend/ellis/rules/engine.py` |
| Languages | Every Sonic language and accent, from one list | `backend/config/languages.yaml` |

Run **one** instance: the agent runner and the event bus live in the API process.

## 2. One spoken turn

```mermaid
sequenceDiagram
  autonumber
  participant B as Browser (VoiceClient)
  participant V as VoiceSession
  participant I as Cartesia Ink
  participant L as LlmLiaison
  participant C as case_service + DB
  participant M as Claude
  participant S as Cartesia Sonic

  B->>V: tap mic, talk down
  V->>S: cancel the line being spoken (word cut at, from timestamps)
  V-->>B: stop_audio, state listening
  loop every 100 ms while talking
    B->>V: PCM16 frame (room noise gated out)
    V->>I: frame
    I-->>V: transcript so far
    V-->>B: user_partial (live caption)
  end
  V->>V: 3 s after the last new word, the turn is sent
  V-->>B: user_final, state thinking
  V->>L: handle(text, interrupted word, hesitant?)
  L->>C: safety check and save the utterance
  alt stop topic or spoken ID number
    C-->>L: section set aside for the attorney, or secure entry opened
    L-->>V: fixed pre-written line (Claude never sees the words)
  else normal turn
    L->>C: has the case changed? (latest event id)
    L->>M: turn + live case data + tools
    M-->>L: tool calls (record_fact, read_back, set_focus, ...)
    L->>C: run the tools (checks against documents and rules)
    L->>M: tool results
    M-->>L: reply text
  end
  L-->>V: reply line
  V-->>B: line (text)
  V->>S: speak line in the applicant's accent
  S-->>V: audio chunks + word timestamps
  V-->>B: audio (PCM 24 kHz), then line_end
  L-)C: background: save the line, build next turn's case data
```

## 3. The Creao staff agents

```mermaid
flowchart TB
  E["Event<br/>fact saved, upload, flag, reviewer decision"] --> R["Runner routing table<br/>which agents care"]
  R --> D["Debounce about 3 s<br/>one queued job per case and agent"]
  D --> BUNDLE["Case bundle<br/>facts, documents, deadlines, language<br/>IDs masked, no transcripts, field aliases"]
  BUNDLE --> POST["POST /api/v1/apps/{app_id}/runs<br/>that agent's own API key"]
  POST --> POLL["GET /runs/{id} every 4 s<br/>up to 90 s"]
  POLL --> T{"Translate the agent's output"}
  T -- "case manager: question_queue.json" --> Q["Briefing<br/>what Ellis asks next"]
  T -- "paralegal: JSON in chat text" --> P["Document checks, gaps, review items"]
  T -- "docketing clerk: docket.json" --> K["Deadline findings as tasks"]
  T -- "QA reviewer: qa_findings.json" --> QA["Findings for the attorney"]
  Q --> V["validate_envelope + authority table<br/>disallowed items rejected and logged"]
  P --> V
  K --> V
  QA --> V
  V --> W["apply_proposal<br/>written with provenance"]
  W --> USE["Liaison reads the briefing each turn<br/>clinic sees items in its review queue"]
```

Agents propose; they never write to the case. A run that fails or returns invalid output writes nothing and leaves
a task on the clinic's board.

## 4. Case lifecycle

```mermaid
stateDiagram-v2
  [*] --> consent_pending: clinic creates the case, or the applicant signs up
  consent_pending --> intake: applicant agrees to the disclosure
  intake --> evidence: every required question answered
  evidence --> intake: a new required question
  evidence --> review: no documents missing
  review --> intake: a required answer goes missing
  review --> ready: reviewer marks ready (gate passes)
  ready --> review: a new material fact, or the applicant reopens a section
  ready --> signed: applicant signs, packet built
  signed --> review: an answer changes after signing (signature voided)
  intake --> referred_out: applicant or clinic refers out
  review --> referred_out
  review --> closed: clinic closes the case
  signed --> [*]
```

The ready gate passes only when every required answer is confirmed by the applicant, no blocking review item is
open, the QA memo is newer than the last material change, the rules ran on the current config, and no document is
still being read.

## Safety rules the design enforces

- **Stop topics never reach the model.** Arrest, removal, false citizenship claims, fraud and danger are caught by
  a keyword check in English, Spanish and the applicant's language before Claude sees the turn. Only the category
  is stored; the section is set aside and the case blocked until a licensed professional resolves it.
- **Sensitive numbers are typed, never spoken.** A spoken ID number is removed from the turn and the secure entry
  opens; models only ever see tokens like `[A_NUMBER]`, and the real values live in an AES-GCM vault.
- **Models never compute dates or fees.** The rules engine does, from a versioned config.
- **Nothing is overwritten.** Corrections supersede earlier facts, and the event log is append-only.
- **Audio is not stored.** Only conversation text is saved.
- **Ellis never files.** The clinic reviews and the applicant signs; the applicant or the clinic files with USCIS.
