import type { IncomingMessage, ServerResponse } from "node:http";
import type { Plugin } from "vite";
import { pickReply } from "./replies.ts";

const DELAY_MS = 1200;

function readBody(request: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    request.on("data", (chunk: Buffer) => chunks.push(chunk));
    request.on("end", () => resolve(Buffer.concat(chunks).toString("utf-8")));
    request.on("error", reject);
  });
}

/** Solo per `npm run dev:mock`: risponde a `POST /assistente/api/chat` con due percorsi già calcolati,
 * per vedere l'interfaccia senza il servizio dell'assistente. Non entra nel build. */
export function mockApi(): Plugin {
  return {
    name: "assistant-mock-api",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use(
        "/assistente/api/chat",
        (request: IncomingMessage, response: ServerResponse) => {
          if (request.method !== "POST") {
            response.statusCode = 405;
            response.end();
            return;
          }
          readBody(request)
            .then((raw) => {
              const body = JSON.parse(raw) as { message?: unknown };
              const message = typeof body.message === "string" ? body.message : "";
              setTimeout(() => {
                response.setHeader("Content-Type", "application/json");
                response.end(JSON.stringify(pickReply(message)));
              }, DELAY_MS);
            })
            .catch(() => {
              response.statusCode = 400;
              response.end();
            });
        },
      );
    },
  };
}
