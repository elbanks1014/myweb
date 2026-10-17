import Anthropic from "@anthropic-ai/sdk";

export const MODEL = process.env.AGENT_MODEL || "claude-opus-5-5";

// Real LLM backed by Claude. Streams every request so the supervisor can see
// tokens arriving (onProgress) and tell a working agent from a stuck one.
export class ClaudeLLM {
  constructor({ model = MODEL, effort = process.env.AGENT_EFFORT || "medium" } = {}) {
    this.client = new Anthropic();
    this.model = model;
    this.effort = effort;
  }

  async complete({ system, prompt, schema, signal, onProgress }) {
    const params = {
      model: this.model,
      max_tokens: 64000,
      system,
      messages: [{ role: "user", content: prompt }],
      thinking: { type: "adaptive" },
      output_config: { effort: this.effort },
      // Re-run on Anthropic's recommended fallback model if a request is declined.
      betas: ["server-side-fallback-2026-07-01"],
      fallbacks: "default",
    };
    if (schema) params.output_config.format = { type: "json_schema", schema };

    const stream = this.client.beta.messages.stream(params, { signal });
    stream.on("streamEvent", () => onProgress?.());
    const message = await stream.finalMessage();

    if (message.stop_reason === "refusal") {
      throw new Error(`Model declined the request: ${message.stop_details?.explanation || "no explanation"}`);
    }
    const text = message.content.filter((b) => b.type === "text").map((b) => b.text).join("");
    return schema ? JSON.parse(text) : text;
  }
}

// Offline stand-in so the app (and tests) run with no API key.
// `hangOnce` lets tests simulate an agent that goes silent.
export class MockLLM {
  constructor({ delayMs = 150, hangOnce = new Set() } = {}) {
    this.delayMs = delayMs;
    this.hangOnce = hangOnce; // set of agent names that will hang on their first call
  }

  async complete({ system, prompt, schema, signal, onProgress, agent }) {
    if (agent && this.hangOnce.has(agent)) {
      this.hangOnce.delete(agent);
      await new Promise((_, reject) => {
        if (signal?.aborted) return reject(new Error("aborted"));
        signal?.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
      });
    }
    for (let i = 0; i < 3; i++) {
      await sleep(this.delayMs / 3, signal);
      onProgress?.();
    }
    const task = (prompt.match(/TASK:\s*(.*)/) || [])[1] || "the task";
    if (schema?.properties?.steps) {
      return {
        steps: [
          { title: "Research", instructions: `Gather the key facts needed for: ${task}` },
          { title: "Draft", instructions: `Produce a first draft for: ${task}` },
          { title: "Polish", instructions: `Tighten and format the final deliverable for: ${task}` },
        ],
      };
    }
    if (schema?.properties?.approved) {
      return { approved: true, feedback: "Looks complete and on-task." };
    }
    if (/final report/i.test(system)) return `# Result\n\nMock summary of the crew's work on: ${task}`;
    const step = (prompt.match(/STEP:\s*(.*)/) || [])[1] || "work";
    return `Mock output for step "${step}".`;
  }
}

function sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => { clearTimeout(t); reject(new Error("aborted")); }, { once: true });
  });
}

export function createLLM() {
  const hasKey = process.env.ANTHROPIC_API_KEY || process.env.ANTHROPIC_AUTH_TOKEN;
  if (process.env.AGENT_MODE === "mock" || !hasKey) return new MockLLM();
  return new ClaudeLLM();
}
