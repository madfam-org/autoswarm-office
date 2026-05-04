#!/usr/bin/env node
/**
 * Regenerate `packages/shared-types/src/generated/api.ts` from the
 * nexus-api OpenAPI schema.
 *
 * Usage:
 *   pnpm generate-types
 *
 * The OpenAPI schema is produced by importing the FastAPI app and
 * calling `app.openapi()` — no uvicorn boot, no HTTP listener, no DB
 * connection (lifespan is not invoked when the app is built but never
 * served). All Python imports are run inside `uv run` so the workspace
 * venv is honoured.
 *
 * Schema-drift CI gate (`schema-drift.yml`) runs this same script then
 * `git diff --exit-code` on the generated file. If a Pydantic model or
 * FastAPI route changes without regenerating, the gate fails.
 */

import { execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import openapiTS, { astToString } from 'openapi-typescript';

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(SCRIPT_DIR, '..');
const NEXUS_API_DIR = resolve(REPO_ROOT, 'apps/nexus-api');
const OUTPUT_PATH = resolve(REPO_ROOT, 'packages/shared-types/src/generated/api.ts');

// Inline Python: import the FastAPI app, dump app.openapi() as JSON to
// stdout. We redirect sys.stdout to sys.stderr during the import phase
// so any structlog / print noise does not corrupt the JSON document.
//
// We pass placeholder env vars so pydantic-settings does not abort on
// missing required fields. The lifespan context (DB/Redis ping) only
// runs under uvicorn, never when we just instantiate the app for its
// schema — so the placeholders are never dialled.
const PYTHON_DUMP = [
  'import json',
  'import sys',
  '_real_stdout = sys.stdout',
  'sys.stdout = sys.stderr',
  'from nexus_api.main import create_app',
  'app = create_app()',
  'spec = app.openapi()',
  'sys.stdout = _real_stdout',
  '_real_stdout.write(json.dumps(spec))',
].join('\n');

function dumpOpenApi() {
  const env = {
    ...process.env,
    // Placeholder values — never dialled because lifespan() is not
    // entered during pure-app construction.
    DATABASE_URL:
      process.env.DATABASE_URL ?? 'postgresql+asyncpg://codegen:codegen@localhost:5432/codegen',
    REDIS_URL: process.env.REDIS_URL ?? 'redis://localhost:6379',
    ENVIRONMENT: process.env.ENVIRONMENT ?? 'development',
  };

  const stdout = execFileSync(
    'uv',
    ['run', '--directory', NEXUS_API_DIR, 'python', '-c', PYTHON_DUMP],
    {
      env,
      maxBuffer: 32 * 1024 * 1024,
      // Inherit stderr so any real failure surfaces to the user.
      stdio: ['ignore', 'pipe', 'inherit'],
    },
  );

  return stdout.toString('utf-8');
}

async function main() {
  console.error('[generate-types] Dumping nexus-api OpenAPI schema…');
  const openapiJson = dumpOpenApi();

  let schema;
  try {
    schema = JSON.parse(openapiJson);
  } catch (err) {
    console.error('[generate-types] Failed to parse OpenAPI JSON:', err);
    console.error('[generate-types] First 500 chars of stdout:\n', openapiJson.slice(0, 500));
    process.exit(1);
  }

  const pathCount = Object.keys(schema.paths ?? {}).length;
  const schemaCount = Object.keys(schema.components?.schemas ?? {}).length;
  console.error(
    `[generate-types] Schema OK — ${pathCount} paths, ${schemaCount} component schemas.`,
  );

  console.error('[generate-types] Generating TypeScript AST…');
  const ast = await openapiTS(schema, {
    // Use string-literal unions instead of `enum {}` for cleaner output
    // and to avoid runtime enum objects in pure-type files.
    enum: false,
    // `Record<string, never>` is hostile to consumers — emit `unknown`.
    emptyObjectsUnknown: true,
  });

  const banner = [
    '/**',
    ' * AUTO-GENERATED from nexus-api OpenAPI schema. DO NOT EDIT.',
    ' *',
    ' * Run `pnpm generate-types` to regenerate. CI (schema-drift.yml)',
    ' * fails if this file is out of sync with the FastAPI routes.',
    ' *',
    ' * These are WIRE TYPES (snake_case, mirror the API). Hand-written',
    ' * domain types in sibling files (camelCase) are still the source of',
    ' * truth for React/Phaser; conversion happens at the fetch boundary.',
    ' */',
    '',
    '/* eslint-disable */',
    '',
  ].join('\n');

  const body = astToString(ast);
  const output = banner + body + (body.endsWith('\n') ? '' : '\n');

  mkdirSync(dirname(OUTPUT_PATH), { recursive: true });
  writeFileSync(OUTPUT_PATH, output, 'utf-8');

  console.error(`[generate-types] Wrote ${OUTPUT_PATH} (${output.length.toLocaleString()} bytes).`);
}

main().catch((err) => {
  console.error('[generate-types] Failed:', err);
  process.exit(1);
});
