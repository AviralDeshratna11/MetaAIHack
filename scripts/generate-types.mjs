import { compile } from 'json-schema-to-typescript';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
const schema = JSON.parse(await readFile('packages/schemas/generated/contracts.schema.json', 'utf8'));
const content = await compile(schema, 'Video2RobotContracts', {
  bannerComment: '/* Generated from Pydantic JSON Schema. Run python -m scripts.export_schemas && npm run schemas. */',
  additionalProperties: false,
});
const target = 'apps/web/src/generated/contracts.ts';
if (process.argv.includes('--check')) {
  if (await readFile(target, 'utf8').catch(() => '') !== content) throw new Error('Generated TypeScript is stale');
} else {
  await mkdir('apps/web/src/generated', { recursive: true });
  await writeFile(target, content);
}
