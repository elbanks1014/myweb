# Agent Crew

A small web app where a team of AI agents (powered by Claude) runs your tasks for you, **automatically on a schedule**, talks to each other while it works, and has a **supervisor that won't let the work stall**.

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
- **Still quiet** after twice that → the supervisor stops it and **hands the step to another worker**.
- **Reviewer and worker going back and forth** → after 2 revisions the latest version is accepted so the run keeps moving.
- **Whole run makes no progress** for `RUN_STALL_MINUTES` → the run is stopped and marked failed with the reason.

### Scheduling

Every task has a "run every N minutes" interval. The scheduler starts each task when it's due, never runs the same task twice at once, and keeps the last 100 runs (results and full chat log) in `data/db.json`. You can pause/resume a schedule or press **Run now** anytime.

## Running it

Requires Node.js 20+.

```bash
npm install
export ANTHROPIC_API_KEY=sk-ant-...   # your Claude API key
npm start                             # open http://localhost:3000
```

No API key yet? `npm run demo` runs the whole app with simulated agents so you can see how it works.

### Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | – | Claude API key. Without it the app runs in demo mode. |
| `AGENT_MODEL` | `claude-opus-5-5` | Claude model every agent uses. |
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

Covers a full run, a worker that hangs (nudged → stopped → handed to another worker), reviewer feedback and the revision limit, a run that stalls completely, and the scheduler.

## Project layout

```
src/server.js      HTTP API + live updates (server-sent events)
src/scheduler.js   Task store and the "run every N minutes" scheduler
src/crew.js        One run: plan → work → review → report
src/agents.js      Agent wrapper (prompting, heartbeats, abort)
src/supervisor.js  Stall detection and intervention
src/bus.js         Message bus agents use to talk to each other
src/llm.js         Claude client (streaming) and the offline demo stand-in
public/index.html  Dashboard
```
