import { test } from "node:test";
import assert from "node:assert/strict";
import { runCrew } from "../src/crew.js";
import { MockLLM } from "../src/llm.js";
import { Store, Scheduler } from "../src/scheduler.js";

const task = { id: "t1", name: "Write a haiku about autumn", description: "" };

test("crew plans, works every step, reviews, and reports", async () => {
  const run = await runCrew(task, { llm: new MockLLM({ delayMs: 10 }), workers: 2 });
  assert.equal(run.status, "succeeded");
  assert.equal(run.steps.length, 3);
  assert.ok(run.steps.every((s) => s.status === "done" && s.output));
  // Work is spread across the worker pool.
  assert.deepEqual([...new Set(run.steps.map((s) => s.worker))].sort(), ["Worker-1", "Worker-2"]);
  assert.match(run.result, /haiku about autumn/);
  assert.ok(run.messages.some((m) => m.type === "plan"));
});

test("supervisor nudges a silent agent, stops it, and hands the step to another worker", async () => {
  const llm = new MockLLM({ delayMs: 10, hangOnce: new Set(["Worker-1"]) });
  const run = await runCrew(task, { llm, workers: 2, stallMs: 100, checkMs: 20 });
  assert.equal(run.status, "succeeded");
  const types = run.messages.filter((m) => m.from === "Supervisor").map((m) => m.type);
  assert.ok(types.includes("nudge"), "expected a nudge");
  assert.ok(types.includes("intervene"), "expected an intervention");
  assert.ok(types.includes("handoff"), "expected a handoff");
  assert.equal(run.steps[0].worker, "Worker-2");
  assert.equal(run.steps[0].reassignments, 1);
});

test("a stalled planner is restarted instead of failing the run", async () => {
  const llm = new MockLLM({ delayMs: 10, hangOnce: new Set(["Planner"]) });
  const run = await runCrew(task, { llm, workers: 1, stallMs: 100, checkMs: 20 });
  assert.equal(run.status, "succeeded", run.error);
  assert.ok(run.messages.some((m) => m.type === "handoff" && m.to === "Planner"));
});

test("reviewer feedback goes back to the worker and the revision limit keeps the run moving", async () => {
  const llm = new MockLLM({ delayMs: 5 });
  const base = llm.complete.bind(llm);
  llm.complete = async (args) => args.schema?.properties?.approved
    ? { approved: false, feedback: "Needs more detail." }
    : base(args);
  const run = await runCrew(task, { llm, workers: 1, maxRevisions: 1 });
  assert.equal(run.status, "succeeded");
  assert.ok(run.messages.some((m) => m.type === "feedback" && m.to === "Worker-1"));
  assert.ok(run.messages.some((m) => m.type === "intervene" && /revision limit/.test(m.content)));
  assert.ok(run.steps.every((s) => s.revisions === 1));
});

test("a run with no progress at all is stopped by the supervisor", async () => {
  const llm = new MockLLM({ hangOnce: new Set(["Planner"]) });
  const run = await runCrew(task, { llm, workers: 1, stallMs: 10_000, runStallMs: 100, checkMs: 20 });
  assert.equal(run.status, "failed");
  assert.match(run.error, /no progress/);
});

test("scheduler runs due tasks and schedules the next run", async () => {
  const scheduler = new Scheduler({ store: new Store(null), models: { demo: { label: "Demo", llm: new MockLLM({ delayMs: 5 }) } }, tickMs: 60_000 });
  const t = scheduler.addTask({ name: "Daily digest", intervalMinutes: 30 });
  const done = new Promise((resolve) => scheduler.on("tasks", () => t.lastStatus && resolve()));
  scheduler.start();
  await done;
  scheduler.stop();
  assert.equal(t.lastStatus, "succeeded");
  assert.equal(t.model, "demo");
  assert.equal(scheduler.store.data.runs.length, 1);
  assert.equal(scheduler.store.data.runs[0].model, "Demo");
  assert.ok(t.nextRunAt - Date.now() > 29 * 60_000);
});

test("scheduler rejects a model that isn't configured", () => {
  const scheduler = new Scheduler({ store: new Store(null), models: { demo: { label: "Demo", llm: new MockLLM() } } });
  assert.throws(() => scheduler.addTask({ name: "x", model: "claude" }), /Unknown model "claude"/);
});
