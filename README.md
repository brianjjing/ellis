# Ellis

Ellis is a agentic immigration assistant built for small legal clinics to help individuals navigate the U.S naturalization process. 

## Inspiration

The U.S naturalization process is incredibly difficult to navigate, the bureaucracy behind the N-400 form is incredibly confusing, the process requires you to remember obscure details from years ago, and for those whose first language isn't English naturalization is a nightmare. Additionally, this story is personal to us as a team, as several of our parents have gone/are currently going through this arduous process, and like most Americans-to-be they found it incredibly frustrating and had to consult legal clinics for advice. Unfortunately, smaller legal clinics who typically help those within their communities are become more overwhelmed by the day, and either have to make people wait incredibly long times for appointments, or have to turn them away all together. 

## What it does

An applicant talks through their case in a language of their choice at their own pace instead of filling out forms, and Cartesia's voice agent carries the entire conversation, with turn detection for natural back-and-forth and word-level timestamps so interrupting Ellis mid-sentence4 cuts it off where you started talking. Every fact gets checked as it's said. For example, a hedged answer triggers a read-back before it's trusted, a stated fact that needs a document opens a gap on the case, and anything touching a serious issue (arrest, removal, fraud) halts the session immediately for attorney review, meaning no AI judgment call. Behind that single conversation, four highly specialized and trained Creao legal agents work the case like a real legal team. A case manager coordinates the file, a document paralegal checks uploads against stated facts, a docketing clerk tracks deadlines, and a QA reviewer does a final pass. Each proposes changes through a typed, authority-checked API rather than writing to the case directly. The clinic's attorneys review everything flagged before the applicant signs off. Ellis never tells someone they qualify, and it never files anything itself, rather it just guides the person through the process and does the unglamorous labor for them a legal clinic can use. 

## How we built it

A React.js app hosted on Vercel has the Cartesia voice agent as the main interface the user interacts with. Cartesia's Ink-2 does  streaming speech-to-text over a websocket, with turn detection (turn.start/turn.end) driving barge-in and end-of-turn — no push-to-talk button needed to know when someone's finished speaking. Replies go out through Sonic streaming text-to-speech with word-level timestamps (add_timestamps: true), which is what lets an applicant interrupt mid-sentence and have playback cut exactly at the word they started talking over, not the next audio chunk boundary. A tap starts a turn by streaming mic PCM16 and sending talk-down; release (or Ink's own turn.end) closes it. Three categories of line are locked and never interruptible by design: the consent disclosure, the stop-now safety script, and secure-entry prompts. The same Claude-driven liaison is also wired up as a Cartesia Line Agent (line_app.py, metadata.case_id), callable with ELLIS_LINE_BRAIN=llm for an LlmAgent behind HTTP tools. 

On the backend, a team of four specialized Creao agents runs to actually fill out the naturalization forms, create case books, and give communication to Cartesia on what needs to be followed up on or asked. The case manager, document paralegal, docketing clerk, and QA reviewer are each their own Creao app with their own API key and app ID, with custom playbooks adapted from Harvey's Legal Agent Benchmark(LAB) task patterns. We chose LAB to give context to our Creao agents because the benchmark's tasks are written by actual lawyers, and we wanted to ensure our agents had the context to actually assist with naturalization. From there, we further fine-tuned each agent into a specialized legal employee by giving a prompt based on the relevant tasks from the benchmark, as well as specific tools we created in the backend that each agent has access to in order to not only do the naturalization work, but also to communicate with Cartesia. In this case, some of the tools included were a fact checker that would check what the user was saying compared to what their documents said, document parsers, as well as communication tools to ensure Cartesia knew what to ask and when to ask. 

Our backend calls each agent directly (POST .../apps/<app_id>/runs, polling GET .../runs/<id> until it leaves pending/running), then translates whatever native shape that agent's engine returns — a fenced JSON block in chat text for some, a downloadable artifact file for others — into one typed proposal envelope. Authority is enforced in our own code, not just assumed from the prompt: a dict keyed by agent name defines exactly which item types and kinds each one may propose, and anything outside that gets rejected and logged, not silently dropped. Agents propose; they never write to the case directly. We also wired a rough Gmail integration ourselves (not through Creao's own connector) — a hedged travel date triggers a consent question, and only on a yes does it search for a confirming email, surfacing whatever it finds as a candidate for voice read-back, never as a written fact.

Everything else is a straightforward FastAPI + React stack, Python 3.12 with uv, Postgres in production, React + Vite + TypeScript on the frontend. The case itself is an append-only event log, not a mutable row — corrections supersede, they never overwrite. Dates, deadlines, and fee math run through a pure rules engine with a versioned config; no model ever computes a date. Document extraction runs in a sandboxed subprocess with no DB credentials. And the one rule that holds everywhere, for every agent and every tool: nothing an AI finds — a document match, a search result — becomes a confirmed fact without the applicant hearing it read back and saying yes out loud. That's enforced by the schema itself, not left to a prompt instruction.

Agents (IDs and links): Case manager: f34f8806-2859-47bb-bd13-2e2745df9da6, Document paralegal: 72a8da32-5d0b-43bb-8444-6bac87d7aa28, Docketing clerk: eac1bd98-c08a-441e-b1bd-97e29c33f0cb, QA reviewer: 95f10378-bceb-4b2d-9376-e75f5cca3906. Install links are in the Try it out section; run share links: Case manager run: https://agent.creao.ai/install/f34f8806-2859-47bb-bd13-2e2745df9da6?version=c7684901-ea53-4e5e-815d-b36fd6aae9d7, Document paralegal run: https://agent.creao.ai/install/72a8da32-5d0b-43bb-8444-6bac87d7aa28?version=c7664e28-c9d8-426a-bbd4-448e2f1ae7df, Docketing clerk run: https://agent.creao.ai/install/eac1bd98-c08a-441e-b1bd-97e29c33f0cb?version=b766e0c9-4cd9-4d0a-99bb-4c51ced3427a, QA reviewer run: https://agent.creao.ai/install/95f10378-bceb-4b2d-9376-e75f5cca3906?version=6832ec16-ed7e-4dc4-82fa-f675cffd200d

## Why We Built It This Way

We wanted the entire experience to feel seamless for those whose first language wasn't English, which is why we chose Cartesia since it can support several languages and locales, and why we are happy to show in the live demo on Sunday that our application supports several languages. Additionally, considering many are unsure about information they give during naturalization since many of it is obscure or from years ago, we also wanted voice agent software that can detect uncertainty and follow up on it. For the backend, we used a team of Creao legal agents because we wanted a way to easily deploy specialized agents that can not only do the work for naturalization, but also communicate with Cartesia to ensure its asking the right questions. The entire project would break without Creao because otherwise we wouldn't have been able to focus on making each agent incredibly specialized, the no code prompt and deploy via an API made the entire process very easy so we could instead focus on making each agent as specialized as possible. 


## Challenges we ran into

*Initial iterations of Cartesia voice agent conversation felt like the agent was reading off a checklist instead of having real conversation
*Cartesia's voice agent was too sensitive to background noise, so we created a toggle to talk feature, implemented a decible based system to find out who the main speaker was, 
*The web application had several bugs causing Spanish to be hardcoded into text displayed on the website
*Creao's MCP connectors intially refused to connect cleanly, and required outside API keys that wouldn't register
*Creao's playbook and agents would sometimes not save causing us to restart progress

## Accomplishments that we're proud of

*The Creao agents are incredibly good at the tasks they do because of the legal agentic benchmark tasks used to create them and work incredibly well together
*The Creao legal agentic team backend is able to seamlessly communicate with the Cartesia voice agent to guide it on questions to ask
*The Cartesia voice agent flows seamlessly within conversation and feels like you're talking to a real person
*The Cartesia voice agent logic we built deals with background noise very effectively and can spot uncertainty in wordage easily

## What we learned

*A third-party agent platform having a tool connected doesn't mean the agent's own instructions were ever told to use it, we confirmed this when one agent reported its Gmail connector was active and still never used it, because nothing in its prompt said when to
*Altough it didn't relate to the sponsor track products themselves, we learned that developing on multiple seperate tracks and merging them later ended up being the most effective strategy for us

## What's next

Moving into other parts of the immigration process such as Visas or aslyum, as well as reaching out the small legal clinics to test our product more and see how it works in real work enviornments. 

## Try it out

