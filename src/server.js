import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createModels } from "./llm.js";
import { Store, Scheduler, summarize } from "./scheduler.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT) || 3000;
const DATA_FILE = process.env.DATA_FILE || path.join(here, "..", "data", "db.json");

const { models, defaultModel } = createModels();
const store = new Store(DATA_FILE);
const scheduler = new Scheduler({
  store,
  models,
  defaultModel,
  crewOptions: {
    stallMs: Number(process.env.STALL_SECONDS || 90) * 1000,
    runStallMs: Number(process.env.RUN_STALL_MINUTES || 15) * 60_000,
  },
});

// Server-sent events: live agent chatter + run/task updates for the dashboard.
const clients = new Set();
const broadcast = (event, data) => {
  const payload = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
  for (const res of clients) res.write(payload);
};
scheduler.on("message", (m) => broadcast("message", m));
scheduler.on("run", (r) => broadcast("run", r));
scheduler.on("tasks", () => broadcast("tasks", tasksView()));

function tasksView() {
  return store.data.tasks.map((t) => ({ ...t, running: scheduler.running.has(t.id) }));
}

async function readBody(req) {
  let body = "";
  for await (const chunk of req) body += chunk;
  return body ? JSON.parse(body) : {};
}

function send(res, status, data) {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(data));
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  const parts = url.pathname.split("/").filter(Boolean);
  try {
    if (req.method === "GET" && url.pathname === "/") {
      res.writeHead(200, { "content-type": "text/html" });
      return fs.createReadStream(path.join(here, "..", "public", "index.html")).pipe(res);
    }
    if (url.pathname === "/api/events") {
      res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache", connection: "keep-alive" });
      res.write(`event: tasks\ndata: ${JSON.stringify(tasksView())}\n\n`);
      clients.add(res);
      req.on("close", () => clients.delete(res));
      return;
    }
    if (url.pathname === "/api/info") {
      return send(res, 200, { defaultModel, models: Object.entries(models).map(([id, m]) => ({ id, label: m.label })) });
    }
    if (parts[0] === "api" && parts[1] === "tasks") {
      const id = parts[2];
      if (req.method === "GET" && !id) return send(res, 200, tasksView());
      if (req.method === "POST" && !id) return send(res, 201, scheduler.addTask(await readBody(req)));
      if (req.method === "PATCH" && id) return send(res, 200, scheduler.updateTask(id, await readBody(req)));
      if (req.method === "DELETE" && id) { scheduler.deleteTask(id); return res.writeHead(204).end(); }
      if (req.method === "POST" && id && parts[3] === "run") {
        scheduler.getTask(id);
        scheduler.runNow(id).catch((err) => console.error(err));
        return send(res, 202, { started: true });
      }
    }
    if (req.method === "GET" && parts[0] === "api" && parts[1] === "runs") {
      if (!parts[2]) return send(res, 200, store.data.runs.slice(0, 30).map(summarize));
      const run = store.data.runs.find((r) => r.id === parts[2]);
      return run ? send(res, 200, run) : send(res, 404, { error: "Run not found." });
    }
    send(res, 404, { error: "Not found." });
  } catch (err) {
    send(res, err.status || 400, { error: err.message });
  }
});

server.listen(PORT, () => {
  scheduler.start();
  console.log(`Agent Crew running at http://localhost:${PORT}`);
  console.log(`Models: ${Object.values(models).map((m) => m.label).join(", ")} — default for new tasks: ${models[defaultModel].label}`);
});
