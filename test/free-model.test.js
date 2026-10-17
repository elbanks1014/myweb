import { test, after } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import { OpenAICompatLLM } from "../src/llm.js";
import { runCrew } from "../src/crew.js";

// Fake OpenAI-compatible server (the API shape Ollama, OpenRouter and Groq expose).
// It streams replies in small chunks, wraps JSON in code fences like many small
// models do, and can be told to hang.
const requests = [];
let hang = false;
const server = http.createServer(async (req, res) => {
  let body = "";
  for await (const c of req) body += c;
  const { messages, model, stream } = JSON.parse(body);
  requests.push({ url: req.url, model, stream, auth: req.headers.authorization, messages });
  if (hang) return; // never answer
  const prompt = messages.at(-1).content;
  let reply = "Here is the step output.";
  if (prompt.includes('"steps"')) reply = 'Sure!\n```json\n{"steps":[{"title":"Outline","instructions":"Outline it"},{"title":"Write","instructions":"Write it"}]}\n```';
  else if (prompt.includes('"approved"')) reply = '{"approved": true, "feedback": "Good."}';
  else if (/final report/i.test(messages[0].content) && prompt.includes("finished every step")) reply = "Final report from the free model.";
  res.writeHead(200, { "content-type": "text/event-stream" });
  for (let i = 0; i < reply.length; i += 7) {
    res.write(`data: ${JSON.stringify({ choices: [{ delta: { content: reply.slice(i, i + 7) } }] })}\n\n`);
  }
  res.end("data: [DONE]\n\n");
});
await new Promise((r) => server.listen(0, r));
const baseUrl = `http://localhost:${server.address().port}/v1`;
after(() => { server.closeAllConnections(); server.close(); });

const task = { id: "t", name: "Write a limerick", description: "" };

test("a full crew run works on a free OpenAI-compatible model", async () => {
  requests.length = 0;
  const llm = new OpenAICompatLLM({ baseUrl, model: "llama3.2", apiKey: "free-key" });
  const run = await runCrew(task, { llm, workers: 2 });
  assert.equal(run.status, "succeeded", run.error);
  assert.deepEqual(run.steps.map((s) => s.title), ["Outline", "Write"]); // parsed despite code fences
  assert.equal(run.result, "Final report from the free model.");
  assert.ok(requests.every((r) => r.url === "/v1/chat/completions" && r.model === "llama3.2" && r.stream && r.auth === "Bearer free-key"));
});

test("a clear error when the free model server isn't running", async () => {
  const llm = new OpenAICompatLLM({ baseUrl: "http://localhost:1/v1" });
  const run = await runCrew(task, { llm, workers: 1 });
  assert.equal(run.status, "failed");
  assert.match(run.error, /Can't reach the free model/);
});

test("supervisor stops a hung free model instead of waiting forever", async () => {
  hang = true;
  try {
    const llm = new OpenAICompatLLM({ baseUrl });
    const run = await runCrew(task, { llm, workers: 1, stallMs: 50, runStallMs: 60_000, checkMs: 10 });
    assert.equal(run.status, "failed");
    assert.match(run.error, /Planner stalled 3 times while planning/);
    assert.equal(run.messages.filter((m) => m.type === "nudge").length, 3);
  } finally {
    hang = false;
  }
});
