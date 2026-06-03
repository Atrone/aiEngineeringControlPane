import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const srcDir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const skipFiles = new Set([
  'main.tsx',
  'test/setup.ts',
  'test/fixtures.ts',
  'test/functionCoverage.ts',
  'types/controlPane.ts',
]);

/**
 * Walks the frontend source tree and returns analyzable TypeScript files.
 */
export function collectSourceFiles(directory: string, files: string[] = []): string[] {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const fullPath = path.join(directory, entry.name);

    if (entry.isDirectory()) {
      if (entry.name === 'test') {
        continue;
      }
      collectSourceFiles(fullPath, files);
      continue;
    }

    if (!/\.(ts|tsx)$/.test(entry.name)) {
      continue;
    }

    if (entry.name.endsWith('.test.ts') || entry.name.endsWith('.test.tsx')) {
      continue;
    }

    files.push(fullPath);
  }

  return files;
}

/**
 * Returns a stable relative path for reporting coverage gaps.
 */
export function toRelativePath(filePath: string): string {
  return path.relative(srcDir, filePath).replace(/\\/g, '/');
}

/**
 * Collects every named function declaration in a source file, including nested handlers.
 */
export function collectFunctions(filePath: string): string[] {
  const relativePath = toRelativePath(filePath);

  if (skipFiles.has(relativePath)) {
    return [];
  }

  const sourceText = fs.readFileSync(filePath, 'utf8');
  const sourceFile = ts.createSourceFile(
    filePath,
    sourceText,
    ts.ScriptTarget.Latest,
    true,
    filePath.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  const functions: string[] = [];
  const stack: string[] = [];

  /**
   * Records a named function and walks nested declarations.
   */
  function visit(node: ts.Node): void {
    if (ts.isFunctionDeclaration(node) && node.name) {
      const qualifiedName = [...stack, node.name.text].join('.');
      functions.push(`${relativePath}:${qualifiedName}`);
      stack.push(node.name.text);
      ts.forEachChild(node, visit);
      stack.pop();
      return;
    }

    if (ts.isVariableStatement(node)) {
      for (const declaration of node.declarationList.declarations) {
        if (
          declaration.name
          && ts.isIdentifier(declaration.name)
          && declaration.initializer
          && (ts.isArrowFunction(declaration.initializer) || ts.isFunctionExpression(declaration.initializer))
        ) {
          const qualifiedName = [...stack, declaration.name.text].join('.');
          functions.push(`${relativePath}:${qualifiedName}`);
        }
      }
    }

    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
  return functions;
}

/**
 * Loads all frontend unit test source for reference matching.
 */
export function loadTestSource(): string {
  const testFiles = collectSourceFiles(srcDir)
    .concat(
      fs
        .readdirSync(path.join(srcDir, 'test'))
        .filter((entry: string) => entry.endsWith('.test.ts') || entry.endsWith('.test.tsx'))
        .map((entry: string) => path.join(srcDir, 'test', entry)),
    )
    .concat(
      fs
        .readdirSync(srcDir, { recursive: true })
        .filter((entry): entry is string => typeof entry === 'string')
        .filter((entry) => entry.endsWith('.test.ts') || entry.endsWith('.test.tsx'))
        .map((entry) => path.join(srcDir, entry)),
    );

  const uniqueTestFiles = Array.from(new Set(testFiles));
  return uniqueTestFiles.map((filePath) => fs.readFileSync(filePath, 'utf8')).join('\n');
}

/**
 * Extracts the bare function name from a qualified coverage entry.
 */
export function getFunctionName(qualifiedEntry: string): string {
  const qualifiedPath = qualifiedEntry.includes(':') ? qualifiedEntry.split(':')[1] : qualifiedEntry;
  const segments = qualifiedPath.split('.');
  return segments[segments.length - 1] ?? qualifiedPath;
}

/**
 * Determines whether a function name appears referenced in the unit test suite.
 */
export function hasTestReference(qualifiedEntry: string, testSource: string): boolean {
  const functionName = getFunctionName(qualifiedEntry);
  const qualifiedPath = qualifiedEntry.includes(':') ? qualifiedEntry.split(':')[1] : qualifiedEntry;
  const patterns = [qualifiedEntry, qualifiedPath, functionName, `test_${functionName}(`];

  if (patterns.some((pattern) => testSource.includes(pattern))) {
    return true;
  }

  return new RegExp(`\\b${functionName.replace(/\$/g, '\\$')}\\b`).test(testSource);
}

/**
 * Returns frontend functions that do not appear referenced by unit tests.
 */
export function findMissingFunctionReferences(): string[] {
  const allFunctions = collectSourceFiles(srcDir).flatMap(collectFunctions);
  const testSource = loadTestSource();
  return allFunctions.filter((entry) => !hasTestReference(entry, testSource));
}
