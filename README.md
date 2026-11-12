# Agent Crew

A small web app where a team of AI agents (powered by Claude, or a free model) runs your tasks for you, **automatically on a schedule**, talks to each other while it works, and has a **supervisor that won't let the work stall**.

## How it works

Each run of a task uses this crew:

| Agent | Job |
|---|---|
| **Planner** | Breaks the task into 2–6 steps, then writes the final report from the results. |
| **Workers** (1–5) | Do the steps, taking turns. Each worker sees the work done so far and every message teammates sent it. |
| **Reviewer** | Checks each step. If it isn't good enough, it sends specific feedback to the worker, who revises. |
| **Supervisor** | Watchdog. Watches every agent's heartbeat (each streamed token counts) and steps in when things stop moving. |

All agents share a message bus, so you can watch them talk in the dashboard's **Live team chat**.

### How stalls are handled

- **Agent goes quiet** for `STALL_SECONDS` → the supervisor sends it a nudge.
- **Still quiet** after twice that → the supervisor stops it and **hands the step to another worker** (the planner and reviewer are restarted instead, up to twice).
- **Reviewer and worker going back and forth** → after 2 revisions the latest version is accepted so the run keeps moving.
- **Whole run makes no progress** for `RUN_STALL_MINUTES` → the run is stopped and marked failed with the reason.

### Scheduling

Every task has a "run every N minutes" interval. The scheduler starts each task when it's due, never runs the same task twice at once, and keeps the last 100 runs (results and full chat log) in `data/db.json`. You can pause/resume a schedule or press **Run now** anytime.

## Running it

Requires Node.js 20+.

```bash
npm install
npm start          # then open http://localhost:3000
```

To use Claude, set your API key before `npm start`:

| Windows (Command Prompt) | Windows (PowerShell) | Mac / Linux |
|---|---|---|
| `set ANTHROPIC_API_KEY=sk-ant-...` | `$env:ANTHROPIC_API_KEY="sk-ant-..."` | `export ANTHROPIC_API_KEY=sk-ant-...` |

The other settings below are set the same way.

No API key yet? `npm run demo` runs the whole app with simulated agents so you can see how it works.

### Using a free model

Each task has a **Model** dropdown, so you can run some tasks on Claude and others on a free model. The free option works with any OpenAI-compatible API:

**Ollama (runs on your computer, completely free, no account):**
```bash
# install from https://ollama.com, then:
ollama pull llama3.2
npm start          # pick "Free (llama3.2)" in the Model dropdown
```

**Free cloud models (no powerful computer needed), e.g. OpenRouter or Groq:**
```bash
# OpenRouter: get a free key at openrouter.ai, pick any model whose id ends in ":free"
export FREE_LLM_URL=https://openrouter.ai/api/v1
export FREE_LLM_API_KEY=sk-or-...
export FREE_LLM_MODEL=<some-model>:free

# or Groq's free tier: key from console.groq.com
export FREE_LLM_URL=https://api.groq.com/openai/v1
export FREE_LLM_API_KEY=gsk_...
export FREE_LLM_MODEL=<a model listed in your Groq console>
npm start
```

Free models are smaller than Claude, so expect simpler results. Free cloud tiers also have rate limits, so a task running every few minutes may get errors; give it a longer interval. If a local model is slow to load the first time, the supervisor may nudge it. That's normal, and raising `STALL_SECONDS` stops the nudges.

### Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | – | Claude API key. Without it, Claude isn't offered in the Model dropdown. |
| `AGENT_MODE` | auto | Default model for new tasks: `claude`, `free` or `mock` (demo). Auto picks Claude if a key is set, else Free if `FREE_LLM_URL` is set, else Demo. |
| `FREE_LLM_URL` | `http://localhost:11434/v1` | OpenAI-compatible endpoint for the free model (default is local Ollama). |
| `FREE_LLM_MODEL` | `llama3.2` | Free model name. |
| `FREE_LLM_API_KEY` | – | Key for free cloud services (not needed for Ollama). |
| `AGENT_MODEL` | `claude-opus-5-5` | Claude model used by tasks set to Claude. |
| `AGENT_EFFORT` | `medium` | `low` / `medium` / `high` / `xhigh` / `max`. Higher is more thorough but slower and costs more. |
| `STALL_SECONDS` | `90` | Silence before an agent is nudged (it's stopped and replaced after 2×). |
| `RUN_STALL_MINUTES` | `15` | No completed step for this long stops the run. |
| `PORT` | `3000` | Web server port. |
| `DATA_FILE` | `data/db.json` | Where tasks and run history are saved. |

**Cost note:** every run makes several Claude calls (plan + one per step + one review per attempt + the final report). A task set to run every few minutes adds up quickly, so pick intervals that match how often you actually need the result.

## Tests

```bash
npm test
```

Covers a full run, a worker that hangs (nudged → stopped → handed to another worker), a stalled planner being restarted, reviewer feedback and the revision limit, a run that stalls completely, the scheduler, and the free-model client (streaming, JSON parsing, unreachable server, hung server) against a fake OpenAI-compatible server.

## Project layout

```
src/server.js      HTTP API + live updates (server-sent events)
src/scheduler.js   Task store and the "run every N minutes" scheduler
src/crew.js        One run: plan → work → review → report
src/agents.js      Agent wrapper (prompting, heartbeats, abort)
src/supervisor.js  Stall detection and intervention
src/bus.js         Message bus agents use to talk to each other
src/llm.js         Claude client, free-model (OpenAI-compatible) client, demo stand-in
public/index.html  Dashboard
```
