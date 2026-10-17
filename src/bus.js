import { EventEmitter } from "node:events";
import { randomUUID } from "node:crypto";

// Shared message bus for one run. Every agent can post to a specific agent
// ("to": name) or to everyone ("to": "all"). The full log is kept so it can be
// shown in the dashboard and fed back into agents' prompts.
export class MessageBus extends EventEmitter {
  constructor(runId) {
    super();
    this.runId = runId;
    this.log = [];
  }

  send({ from, to = "all", type = "chat", content }) {
    const msg = { id: randomUUID(), runId: this.runId, at: Date.now(), from, to, type, content };
    this.log.push(msg);
    this.emit("message", msg);
    return msg;
  }

  // Messages an agent should see: addressed to it or broadcast, excluding its own.
  inbox(name, limit = 12) {
    return this.log.filter((m) => m.from !== name && (m.to === name || m.to === "all")).slice(-limit);
  }
}

export function formatInbox(messages) {
  if (!messages.length) return "(no messages yet)";
  return messages.map((m) => `[${m.type}] ${m.from} -> ${m.to}: ${m.content}`).join("\n");
}
