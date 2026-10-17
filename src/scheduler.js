import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { EventEmitter } from "node:events";
import { runCrew } from "./crew.js";

const MAX_RUNS_KEPT = 100;

// Tiny JSON-file store for tasks and run history.
export class Store {
  constructor(file) {
    this.file = file;
    this.data = { tasks: [], runs: [] };
    if (file && fs.existsSync(file)) this.data = JSON.parse(fs.readFileSync(file, "utf8"));
  }

  save() {
    if (!this.file) return;
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    fs.writeFileSync(this.file, JSON.stringify(this.data, null, 2));
  }
}

// Fires each enabled task every `intervalMinutes`, never overlapping a task with itself.
export class Scheduler extends EventEmitter {
  constructor({ store, llm, tickMs = 5_000, crewOptions = {} }) {
    super();
    Object.assign(this, { store, llm, tickMs, crewOptions });
    this.running = new Map(); // taskId -> live run record
    this.timer = null;
  }

  start() {
    // Runs that were mid-flight when the process died will never finish.
    for (const r of this.store.data.runs) if (r.status === "running") { r.status = "failed"; r.error = "Server restarted during run."; }
    this.store.save();
    this.timer = setInterval(() => this.tick(), this.tickMs);
    this.tick();
  }

  stop() {
    clearInterval(this.timer);
  }

  tick() {
    const now = Date.now();
    for (const task of this.store.data.tasks) {
      if (task.enabled && task.nextRunAt && task.nextRunAt <= now && !this.running.has(task.id)) {
        this.runNow(task.id).catch((err) => console.error(err));
      }
    }
  }

  addTask({ name, description = "", intervalMinutes = 60, workers = 2, enabled = true, runImmediately = true }) {
    if (!name?.trim()) throw new Error("Task name is required.");
    const task = {
      id: randomUUID(),
      name: name.trim(),
      description,
      intervalMinutes: Math.max(1, Number(intervalMinutes) || 60),
      workers: Math.min(5, Math.max(1, Number(workers) || 2)),
      enabled,
      createdAt: Date.now(),
      lastRunAt: null,
      lastStatus: null,
      nextRunAt: runImmediately ? Date.now() : Date.now() + Math.max(1, Number(intervalMinutes) || 60) * 60_000,
    };
    this.store.data.tasks.push(task);
    this.store.save();
    this.emit("tasks");
    if (this.timer) this.tick();
    return task;
  }

  updateTask(id, patch) {
    const task = this.getTask(id);
    for (const key of ["name", "description", "intervalMinutes", "workers", "enabled"]) {
      if (key in patch) task[key] = patch[key];
    }
    if (patch.enabled && !task.nextRunAt) task.nextRunAt = Date.now();
    this.store.save();
    this.emit("tasks");
    return task;
  }

  deleteTask(id) {
    this.store.data.tasks = this.store.data.tasks.filter((t) => t.id !== id);
    this.store.save();
    this.emit("tasks");
  }

  getTask(id) {
    const task = this.store.data.tasks.find((t) => t.id === id);
    if (!task) throw Object.assign(new Error("Task not found."), { status: 404 });
    return task;
  }

  async runNow(id) {
    const task = this.getTask(id);
    if (this.running.has(id)) return this.running.get(id);
    task.nextRunAt = Date.now() + task.intervalMinutes * 60_000;
    this.running.set(id, { taskId: id, status: "starting" });
    this.emit("tasks");

    const run = await runCrew(task, {
      llm: this.llm,
      workers: task.workers,
      ...this.crewOptions,
      onMessage: (m) => this.emit("message", m),
      onUpdate: (r) => { this.running.set(id, r); this.emit("run", summarize(r)); },
    });

    this.running.delete(id);
    task.lastRunAt = run.finishedAt;
    task.lastStatus = run.status;
    this.store.data.runs.unshift(run);
    this.store.data.runs.length = Math.min(this.store.data.runs.length, MAX_RUNS_KEPT);
    this.store.save();
    this.emit("tasks");
    return run;
  }
}

export function summarize(run) {
  const { messages, ...rest } = run;
  return { ...rest, messageCount: messages?.length ?? 0 };
}
