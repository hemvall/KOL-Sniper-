#!/usr/bin/env node
import http from "node:http";
import { build, safeBuilderError } from "./pump_builder.mjs";

const host = process.env.BUILDER_HOST || "127.0.0.1";
const port = Number(process.env.BUILDER_PORT || 8788);
const maxBodyBytes = 16 * 1024;

function respond(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    "content-type": "application/json",
    "content-length": Buffer.byteLength(body),
    "cache-control": "no-store",
  });
  response.end(body);
}

const server = http.createServer((request, response) => {
  if (request.method === "GET" && request.url === "/health") {
    respond(response, 200, { ok: true });
    return;
  }
  if (request.method !== "POST" || request.url !== "/build") {
    respond(response, 404, { ok: false, error: "not found" });
    return;
  }
  let size = 0;
  const chunks = [];
  request.on("data", (chunk) => {
    size += chunk.length;
    if (size > maxBodyBytes) request.destroy();
    else chunks.push(chunk);
  });
  request.on("end", async () => {
    try {
      const payload = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      respond(response, 200, await build(payload));
    } catch (error) {
      respond(response, 400, { ok: false, error: safeBuilderError(error) });
    }
  });
});

server.requestTimeout = 10_000;
server.headersTimeout = 5_000;
server.listen(port, host);
