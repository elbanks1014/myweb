import { randomUUID } from "node:crypto";
import { MessageBus } from "./bus.js";
import { Agent, ROLES } from "./agents.js";
import { Supervisor } from "./supervisor.js";

const PLAN_SCHEMA = {
  type: "object",
  properties: {
    steps: {
      type: "array",
      items: {
        type: "object",
        properties: { title: { type: "string" }, instructions: { type: "string" } },
        required: ["title", "instructions"],
        additionalProperties: false,
      },
    },
  },
  required: ["steps"],
  additionalProperties: false,
};

const REVIEW_SCHEMA = {
  type: "object",
  properties: { approved: { type: "boolean" }, feedback: { type: "string" } },
  required: ["approved", "feedback"],
  additionalProperties: false,
};

// Runs one task end-to-end with a planner, N workers, a reviewer and a supervisor.
// Returns a run record; `onMessage` streams bus traffic to the caller (dashboard).
export async function runCrew(task, { llm, onMessage, onUpdate, workers = 2, maxRevisions = 2, stallMs, runStallMs, checkMs } = {}) {
  const run = {
    id: randomUUID(),
    taskId: task.id,
    taskName: task.name,
    status: "running",
    startedAt: Date.now(),
    finishedAt: null,
    steps: [],
    result: null,
    error: null,
    messages: [],
  };
  const bus = new MessageBus(run.id);
  bus.on("message", (m) => { run.messages.push(m); onMessage?.(m); });

  const make = (name, role) => new Agent({ name, role, instructions: ROLES[role], llm, bus });
  const planner = make("Planner", "planner");
  const reviewer = make("Reviewer", "reviewer");
  const pool = Array.from({ length: Math.max(1, workers) }, (_, i) => make(`Worker-${i + 1}`, "worker"));
  const agents = [planner, reviewer, ...pool];

  let runStalled = false;
  const supervisor = new Supervisor({ bus, agents, stallMs, runStallMs, checkMs, onRunStalled: () => { runStalled = true; } });
  supervisor.start();

  const taskText = `TASK: ${task.name}\nDETAILS: ${task.description || "(none)"}`;

  try {
    // 1. Plan
    const plan = await retryOnStall(planner, bus, {
      work: "planning",
      schema: PLAN_SCHEMA,
      prompt: `${taskText}\n\nBreak this task into 2-6 ordered steps. Each step must be something one worker can complete in a single response.`,
    });
    run.steps = plan.steps.slice(0, 6).map((s) => ({ ...s, status: "pending", output: null, worker: null, revisions: 0, reassignments: 0 }));
    bus.send({ from: "Planner", type: "plan", content: run.steps.map((s, i) => `${i + 1}. ${s.title}`).join("\n") });
    supervisor.progress("Plan ready.");
    onUpdate?.(run);

    // 2. Work each step, with review and stall recovery
    let next = 0;
    for (const [i, step] of run.steps.entries()) {
      const done = run.steps.slice(0, i).map((s, j) => `## Step ${j + 1}: ${s.title}\n${s.output}`).join("\n\n");
      let worker = pool[next++ % pool.length];
      let feedback = "";
      step.status = "running";
      onUpdate?.(run);

      while (true) {
        if (runStalled) throw new Error("Run stopped by supervisor: no progress.");
        step.worker = worker.name;
        let output;
        try {
          output = await worker.think({
            work: `step ${i + 1}: ${step.title}`,
            prompt: `${taskText}\n\nWORK COMPLETED SO FAR:\n${done || "(nothing yet)"}\n\nSTEP: ${step.title}\nINSTRUCTIONS: ${step.instructions}${feedback ? `\n\nREVIEWER FEEDBACK ON YOUR LAST ATTEMPT:\n${feedback}` : ""}`,
          });
        } catch (err) {
          if (err.abortReason === "stalled" && step.reassignments < pool.length + 1) {
            step.reassignments++;
            const replacement = pool.find((w) => w !== worker && w.status !== "working") || worker;
            bus.send({ from: "Supervisor", to: replacement.name, type: "handoff", content: `${worker.name} stalled on "${step.title}". ${replacement.name}, please take it over.` });
            worker = replacement;
            continue;
          }
          throw err;
        }

        const review = await retryOnStall(reviewer, bus, {
          work: `reviewing step ${i + 1}`,
          schema: REVIEW_SCHEMA,
          prompt: `${taskText}\n\nSTEP: ${step.title}\nINSTRUCTIONS: ${step.instructions}\n\nOUTPUT FROM ${worker.name}:\n${output}\n\nApprove if the output fully completes the step. Otherwise give specific feedback.`,
        });

        if (review.approved || step.revisions >= maxRevisions) {
          if (!review.approved) {
            bus.send({ from: "Supervisor", type: "intervene", content: `"${step.title}" hit the revision limit (${maxRevisions}). Accepting the latest version so the run keeps moving.` });
          }
          step.output = output;
          step.status = "done";
          supervisor.progress(`Step ${i + 1}/${run.steps.length} done: ${step.title}`);
          onUpdate?.(run);
          break;
        }
        step.revisions++;
        feedback = review.feedback;
        bus.send({ from: "Reviewer", to: worker.name, type: "feedback", content: review.feedback });
      }
    }

    // 3. Final report
    run.result = await retryOnStall(planner, bus, {
      work: "writing the final report",
      prompt: `${taskText}\n\nYour team finished every step. Write the final report: the finished deliverable for the task, built from the step outputs below.\n\n${run.steps.map((s, j) => `## Step ${j + 1}: ${s.title}\n${s.output}`).join("\n\n")}`,
    });
    run.status = "succeeded";
  } catch (err) {
    run.status = "failed";
    run.error = runStalled ? "Stopped by supervisor: the run made no progress." : err.message;
    bus.send({ from: "Supervisor", type: "error", content: run.error });
  } finally {
    supervisor.stop();
    for (const a of agents) a.abort("run-finished");
    run.finishedAt = Date.now();
    onUpdate?.(run);
  }
  return run;
}

// The planner and reviewer have no stand-in, so when the supervisor stops one
// for stalling, the same agent simply tries again (up to `retries` times).
async function retryOnStall(agent, bus, args, retries = 2) {
  for (let attempt = 0; ; attempt++) {
    try {
      return await agent.think(args);
    } catch (err) {
      if (err.abortReason !== "stalled") throw err;
      if (attempt >= retries) throw new Error(`${agent.name} stalled ${attempt + 1} times while ${args.work}.`);
      bus.send({ from: "Supervisor", to: agent.name, type: "handoff", content: `${agent.name}, starting ${args.work} over after the stall.` });
    }
  }
}
