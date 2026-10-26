// Check exported Next.js method declarations, not string occurrences or app imports.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const spec = JSON.parse(readFileSync(path.join(root, 'contracts/generated/specs/teacher-service-api.json'), 'utf8'));
for (const [endpoint, operations] of Object.entries(spec.paths)) {
  const routePath = endpoint.replace(/\{([^}]+)\}/g, '[$1]');
  const filename = path.join(root, 'teacher_agent/app', routePath, 'route.ts');
  const ast = ts.createSourceFile(filename, readFileSync(filename, 'utf8'), ts.ScriptTarget.Latest, true);
  const handlers = new Map(ast.statements.filter(ts.isFunctionDeclaration).filter(node =>
    node.modifiers?.some(modifier => modifier.kind === ts.SyntaxKind.ExportKeyword),
  ).map(node => [node.name?.text, node]));
  for (const [method, operation] of Object.entries(operations)) {
    if (!['get', 'post', 'put', 'delete', 'patch', 'head', 'options'].includes(method)) continue;
    const handler = handlers.get(method.toUpperCase());
    assert.ok(handler?.body, `Provider missing ${method.toUpperCase()} ${endpoint}`);
    // Explicit apiSuccess(..., 201) must not be silently interpreted as HTTP 200.
    const explicitStatuses = new Set();
    function visit(node) {
      if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 'apiSuccess') {
        const status = node.arguments[1];
        if (!status) explicitStatuses.add('200');
        else {
          assert.ok(ts.isNumericLiteral(status), 'Extend checker for dynamic response status');
          explicitStatuses.add(status.text);
        }
      }
      if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) &&
          node.expression.expression.getText(ast) === 'NextResponse' && node.expression.name.text === 'json') {
        const options = node.arguments[1];
        const status = options && ts.isObjectLiteralExpression(options)
          ? options.properties.find(property => ts.isPropertyAssignment(property) &&
              property.name.getText(ast) === 'status') : undefined;
        if (status && ts.isPropertyAssignment(status)) {
          assert.ok(ts.isNumericLiteral(status.initializer), 'Extend checker for dynamic response status');
          if (Number(status.initializer.text) < 400) explicitStatuses.add(status.initializer.text);
        } else {
          explicitStatuses.add('200');
        }
      }
      ts.forEachChild(node, visit);
    }
    visit(handler.body);
    assert.ok(explicitStatuses.size > 0, `No statically known success response for ${endpoint}`);
    for (const status of explicitStatuses) {
      assert.ok(operation.responses[status], `Undocumented success status ${status}: ${method} ${endpoint}`);
    }
  }
}
console.log('Teacher provider exported methods and explicit success statuses match; auth/body semantics need integration tests.');
