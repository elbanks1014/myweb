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

// Free models through any OpenAI-compatible chat API. Defaults to Ollama running
// locally (no account, no cost); also works with OpenRouter's ":free" models,
// Groq's free tier, LM Studio, etc. by changing FREE_LLM_URL / FREE_LLM_MODEL.
export class OpenAICompatLLM {
  constructor({
    baseUrl = process.env.FREE_LLM_URL || "http://localhost:11434/v1",
    model = process.env.FREE_LLM_MODEL || "llama3.2",
    apiKey = process.env.FREE_LLM_API_KEY,
  } = {}) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.model = model;
    this.apiKey = apiKey;
  }

  async complete({ system, prompt, schema, signal, onProgress }) {
    // Not every free model supports structured output, so describe the JSON
    // shape in the prompt, parse leniently, and ask again once if it's malformed.
    const ask = schema
      ? `${prompt}\n\nRespond with ONLY a JSON object (no prose, no code fences) matching this JSON schema:\n${JSON.stringify(schema)}`
      : prompt;
    let text = await this.chat({ system, prompt: ask, signal, onProgress });
    if (!schema) return text;
    try {
      return parseJson(text);
    } catch {
      text = await this.chat({ system, prompt: `${ask}\n\nYour previous reply was not valid JSON. Reply with the JSON object only.`, signal, onProgress });
      return parseJson(text);
    }
  }

  async chat({ system, prompt, signal, onProgress }) {
    let res;
    try {
      res = await fetch(`${this.baseUrl}/chat/completions`, {
        method: "POST",
        signal,
        headers: { "content-type": "application/json", ...(this.apiKey && { authorization: `Bearer ${this.apiKey}` }) },
        body: JSON.stringify({
          model: this.model,
          stream: true,
          messages: [{ role: "system", content: system }, { role: "user", content: prompt }],
        }),
      });
    } catch (err) {
      if (signal?.aborted) throw err;
      throw new Error(`Can't reach the free model at ${this.baseUrl} (${err.cause?.code || err.message}). Is Ollama running? See README.`);
    }
    if (!res.ok) throw new Error(`Free model returned ${res.status}: ${(await res.text()).slice(0, 300)}`);

    // Server-sent events: "data: {...}" lines, ending with "data: [DONE]".
    const decoder = new TextDecoder();
    let buffer = "";
    let text = "";
    for await (const chunk of res.body) {
      buffer += decoder.decode(chunk, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) {
        const data = line.trim().replace(/^data:\s*/, "");
        if (!line.trim().startsWith("data:") || data === "[DONE]") continue;
        const event = JSON.parse(data);
        if (event.error) throw new Error(`Free model error: ${event.error.message || JSON.stringify(event.error)}`);
        text += event.choices?.[0]?.delta?.content || "";
        onProgress?.();
      }
    }
    return text;
  }
}

function parseJson(text) {
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start === -1 || end < start) throw new Error("No JSON object in model reply.");
  return JSON.parse(text.slice(start, end + 1));
}

// Every model the app can use, keyed by the id stored on each task.
export function createModels() {
  const hasKey = process.env.ANTHROPIC_API_KEY || process.env.ANTHROPIC_AUTH_TOKEN;
  const models = {};
  if (hasKey) {
    const llm = new ClaudeLLM();
    models.claude = { label: `Claude (${llm.model})`, llm };
  }
  const free = new OpenAICompatLLM();
  models.free = { label: `Free (${free.model})`, llm: free };
  models.demo = { label: "Demo (simulated agents)", llm: new MockLLM() };

  // `--demo` instead of AGENT_MODE=mock so `npm run demo` works in the Windows command prompt too.
  const mode = process.argv.includes("--demo") ? "mock" : process.env.AGENT_MODE;
  const wanted = { claude: "claude", free: "free", mock: "demo" }[mode];
  const defaultModel = wanted && models[wanted] ? wanted : hasKey ? "claude" : process.env.FREE_LLM_URL ? "free" : "demo";
  return { models, defaultModel };
}
