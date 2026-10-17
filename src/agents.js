import { formatInbox } from "./bus.js";

// One member of the crew. Wraps every LLM call so that:
//  - the agent's inbox (messages from teammates) is always part of its prompt
//  - every streamed token counts as a heartbeat (lastProgressAt)
//  - the supervisor can abort the call if the agent goes quiet
export class Agent {
  constructor({ name, role, instructions, llm, bus }) {
    Object.assign(this, { name, role, instructions, llm, bus });
    this.status = "idle"; // idle | working | stalled
    this.lastProgressAt = Date.now();
    this.currentWork = null;
    this.nudged = false;
    this.controller = null;
    this.abortReason = null;
  }

  async think({ work, prompt, schema }) {
    this.status = "working";
    this.currentWork = work;
    this.lastProgressAt = Date.now();
    this.nudged = false;
    this.abortReason = null;
    this.controller = new AbortController();
    this.bus.send({ from: this.name, type: "status", content: `Starting: ${work}` });

    const system = `You are ${this.name}, the ${this.role} on a small team of AI agents working together on a task.\n${this.instructions}\nTeammates may message you; take their feedback into account. Be concrete and finish your part.`;
    const fullPrompt = `${prompt}\n\nMESSAGES FROM YOUR TEAM:\n${formatInbox(this.bus.inbox(this.name))}`;

    try {
      const result = await this.llm.complete({
        system,
        prompt: fullPrompt,
        schema,
        agent: this.name,
        signal: this.controller.signal,
        onProgress: () => { this.lastProgressAt = Date.now(); },
      });
      this.bus.send({ from: this.name, type: "status", content: `Finished: ${work}` });
      return result;
    } catch (err) {
      if (this.abortReason) err.abortReason = this.abortReason;
      throw err;
    } finally {
      this.status = this.abortReason === "stalled" ? "stalled" : "idle";
      this.currentWork = null;
      this.controller = null;
    }
  }

  abort(reason) {
    if (!this.controller) return;
    this.abortReason = reason;
    this.controller.abort();
  }
}

export const ROLES = {
  planner: "You break a task into 2-6 clear, ordered steps that workers can complete one at a time, and you write the final report from the team's results.",
  worker: "You complete the step you are assigned. Produce the actual deliverable for the step, not a description of what you would do.",
  reviewer: "You check each step's output against the task. Approve it when it is correct and complete; otherwise give specific, actionable feedback.",
};
