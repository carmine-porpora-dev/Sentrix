import { readFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const ROOT = path.resolve(import.meta.dirname, "../../..");

/** Un percorso a partire dalla radice del repository. */
export function repoPath(...parts: string[]): string {
  return path.join(ROOT, ...parts);
}

export function repoUrl(...parts: string[]): URL {
  return pathToFileURL(repoPath(...parts));
}

export function fixture<T = unknown>(name: string): T {
  const text = readFileSync(repoPath("frontend", "src", "api", "fixtures", name), "utf8");
  return (name.endsWith(".json") ? JSON.parse(text) : text) as T;
}

export interface OpenApiOperation {
  operationId: string;
  parameters?: { name: string; in: string; required?: boolean }[];
  requestBody?: unknown;
}
export interface OpenApi {
  paths: Record<string, Record<string, OpenApiOperation>>;
}

export function openApi(): OpenApi {
  return JSON.parse(readFileSync(repoPath("docs", "spec", "openapi.json"), "utf8")) as OpenApi;
}

export const SCHEMA_FILE = repoPath("frontend", "src", "api", "schema.d.ts");
