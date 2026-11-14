import js from "@eslint/js";
import { defineConfig, globalIgnores } from "eslint/config";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig([
  globalIgnores([
    "dist",
    "playwright-report",
    "test-results",
    "playwright-report-real",
    "test-results-real",
    "coverage",
    "src/api/schema.d.ts",
    "src/styles/*.generated.*",
  ]),
  {
    files: ["**/*.{ts,tsx}"],
    // tseslint.configs.recommended include no-explicit-any (dev-rules 4).
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
    ],
    languageOptions: { ecmaVersion: 2023, globals: globals.browser },
  },
  {
    // gli script girano in Node, non nel browser
    files: ["scripts/**/*.ts"],
    languageOptions: { globals: globals.node },
  },
]);
