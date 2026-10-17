// Watchdog that keeps the crew moving. It never does task work itself; it
// watches heartbeats and intervenes when an agent or the whole run stalls.
//
//  idle > stallMs        -> post a nudge to the agent ("are you still on X?")
//  idle > stallMs * 2    -> abort the agent's call; the crew reassigns the work
//  no progress on the run for runStallMs -> abort the whole run
export class Supervisor {
  constructor({ bus, agents, stallMs = 60_000, runStallMs = 10 * 60_000, checkMs = 2_000, onRunStalled }) {
    Object.assign(this, { bus, agents, stallMs, runStallMs, checkMs, onRunStalled });
    this.name = "Supervisor";
    this.lastRunProgressAt = Date.now();
    this.timer = null;
  }

  start() {
    this.bus.send({ from: this.name, type: "status", content: `Watching ${this.agents.length} agents (nudge after ${fmt(this.stallMs)} of silence).` });
    this.timer = setInterval(() => this.check(), this.checkMs);
  }

  stop() {
    clearInterval(this.timer);
  }

  // The crew calls this whenever a step is completed.
  progress(note) {
    this.lastRunProgressAt = Date.now();
    if (note) this.bus.send({ from: this.name, type: "status", content: note });
  }

  check() {
    const now = Date.now();
    for (const agent of this.agents) {
      if (agent.status !== "working") continue;
      const idle = now - agent.lastProgressAt;
      if (idle > this.stallMs * 2) {
        this.bus.send({ from: this.name, to: agent.name, type: "intervene", content: `No progress from ${agent.name} for ${fmt(idle)} on "${agent.currentWork}". Stopping it and reassigning the work.` });
        agent.abort("stalled");
      } else if (idle > this.stallMs && !agent.nudged) {
        agent.nudged = true;
        this.bus.send({ from: this.name, to: agent.name, type: "nudge", content: `${agent.name}, you've been quiet for ${fmt(idle)} on "${agent.currentWork}". Please wrap up or report a blocker.` });
      }
    }
    if (now - this.lastRunProgressAt > this.runStallMs) {
      this.bus.send({ from: this.name, type: "intervene", content: `The run has made no progress for ${fmt(now - this.lastRunProgressAt)}. Stopping it.` });
      this.stop();
      for (const a of this.agents) a.abort("run-stalled");
      this.onRunStalled?.();
    }
  }
}

function fmt(ms) {
  return ms >= 120_000 ? `${Math.round(ms / 60_000)}m` : `${Math.round(ms / 1000)}s`;
}
