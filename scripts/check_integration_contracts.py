"""Offline integration-contract gate; never imports application modules or .env.

Checks OpenAPI validity and the statically declared provider surface. This does
not prove authorization execution, database semantics, or every response value;
those require isolated integration tests before a runtime implementation switch.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import OpenAPIV31SpecValidator

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("teacher_bridge", "student_bridge", "user_model_config")
METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
CONSTRAINTS = {"min_length": "minLength", "max_length": "maxLength",
               "ge": "minimum", "le": "maximum", "gt": "exclusiveMinimum", "lt": "exclusiveMaximum"}


@dataclass
class Route:
    method: str
    path: str
    function: ast.FunctionDef | ast.AsyncFunctionDef
    functions: dict[str, Any]
    models: dict[str, ast.ClassDef]
    source: str


def function_name(node: ast.AST) -> str:
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else ""


def arguments(function: ast.FunctionDef | ast.AsyncFunctionDef):
    args = function.args
    defaults = [None] * (len(args.args) - len(args.defaults)) + list(args.defaults)
    yield from zip(args.args, defaults)
    yield from zip(args.kwonlyargs, args.kw_defaults)


def type_schema(node: ast.AST) -> dict:
    if isinstance(node, ast.Subscript) and function_name(node.value) == "list":
        return {"type": "array", "items": type_schema(node.slice)}
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left, right = type_schema(node.left), type_schema(node.right)
        def kinds(schema: dict) -> list[str]:
            return schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        return {**left, **{k: v for k, v in right.items() if k != "type"},
                "type": list(dict.fromkeys(kinds(left) + kinds(right)))}
    if isinstance(node, ast.Constant) and node.value is None:
        return {"type": "null"}
    name = function_name(node)
    if name == "UUID":
        return {"type": "string", "format": "uuid"}
    kind = {"str": "string", "int": "integer", "float": "number", "bool": "boolean", "dict": "object"}.get(name)
    if kind:
        return {"type": kind}
    raise ValueError(f"Unsupported provider annotation: {ast.unparse(node)}; extend the checker explicitly.")


def model_schema(model: ast.ClassDef) -> dict:
    properties, required = {}, []
    for field in model.body:
        if not isinstance(field, ast.AnnAssign) or not isinstance(field.target, ast.Name):
            continue
        schema = type_schema(field.annotation)
        default = field.value
        is_required = default is None
        if isinstance(default, ast.Call) and function_name(default.func) == "Field":
            keywords = {kw.arg: kw.value for kw in default.keywords}
            is_required = "default" not in keywords and "default_factory" not in keywords
            if default.args:
                is_required = isinstance(default.args[0], ast.Constant) and default.args[0].value is Ellipsis
            for python_name, json_name in CONSTRAINTS.items():
                if python_name in keywords:
                    field_name = "maxItems" if json_name == "maxLength" and schema["type"] == "array" else json_name
                    schema[field_name] = ast.literal_eval(keywords[python_name])
            if "pattern" in keywords:
                schema["pattern"] = ast.literal_eval(keywords["pattern"])
        properties[field.target.id] = schema
        if is_required:
            required.append(field.target.id)
    return {"type": "object", "properties": properties, "required": required}


def provider_routes(root: Path) -> tuple[dict[tuple[str, str], Route], list[str]]:
    directory = root / "platform/backend/app/api"
    registration = ast.parse((directory / "main.py").read_text(encoding="utf-8-sig"))
    registered = {}
    for expression in registration.body:
        if not isinstance(expression, ast.Expr) or not isinstance(expression.value, ast.Call):
            continue
        call = expression.value
        if function_name(call.func) != "include_router" or not call.args:
            continue
        target = call.args[0]
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
            prefix = next((ast.literal_eval(kw.value) for kw in call.keywords if kw.arg == "prefix"), "")
            registered[target.value.id] = prefix
    result, problems = {}, []
    for source in SOURCES:
        path = directory / "routes" / f"{source}.py"
        module = ast.parse(path.read_text(encoding="utf-8-sig"))
        functions = {node.name: node for node in module.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        models = {node.name: node for node in module.body if isinstance(node, ast.ClassDef)
                  and any(function_name(base) == "BaseModel" for base in node.bases)}
        prefix = registered.get(source, "")
        for node in module.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and function_name(node.value.func) == "APIRouter":
                prefix += next((ast.literal_eval(kw.value) for kw in node.value.keywords if kw.arg == "prefix"), "")
        for function in functions.values():
            for decorator in function.decorator_list:
                if not (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                        and isinstance(decorator.func.value, ast.Name) and decorator.func.value.id == "router"
                        and decorator.func.attr in METHODS and decorator.args):
                    continue
                endpoint = prefix + ast.literal_eval(decorator.args[0])
                if not endpoint.startswith("/internal/"):
                    continue
                if source not in registered:
                    problems.append(f"{source}: internal router is not registered unconditionally")
                key = decorator.func.attr, endpoint
                if key in result:
                    problems.append(f"Duplicate provider route: {key}")
                result[key] = Route(*key, function, functions, models, source)
    student_path = root / "student_agent/backend/internal_platform.py"
    if student_path.is_file():
        main = ast.parse((root / "student_agent/backend/main.py").read_text(encoding="utf-8-sig"))
        registered_student = any(
            isinstance(node, ast.Call) and function_name(node.func) == "include_router"
            and node.args and function_name(node.args[0]) == "internal_platform_router"
            for node in ast.walk(main)
        )
        if not registered_student:
            problems.append("student internal platform router is not registered")
        module = ast.parse(student_path.read_text(encoding="utf-8-sig"))
        functions = {node.name: node for node in module.body
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        models = {node.name: node for node in module.body if isinstance(node, ast.ClassDef)
                  and any(function_name(base) == "BaseModel" for base in node.bases)}
        for function in functions.values():
            for decorator in function.decorator_list:
                if not (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                        and isinstance(decorator.func.value, ast.Name)
                        and decorator.func.value.id == "router"
                        and decorator.func.attr in METHODS and decorator.args):
                    continue
                endpoint = ast.literal_eval(decorator.args[0])
                if not endpoint.startswith("/api/internal/"):
                    continue
                key = decorator.func.attr, endpoint
                if key in result:
                    problems.append(f"Duplicate provider route: {key}")
                result[key] = Route(*key, function, functions, models, "student_internal_platform")
    return result, problems


def declared_headers(route: Route) -> set[str]:
    headers = set()
    for arg, default in arguments(route.function):
        if isinstance(default, ast.Call) and function_name(default.func) == "Header":
            options = {kw.arg: ast.literal_eval(kw.value) for kw in default.keywords}
            header = options.get("alias") or (arg.arg.replace("_", "-") if options.get("convert_underscores", True) else arg.arg)
            headers.add(header.lower())
    return headers


def success_keys(route: Route, function=None, seen=None) -> list[set[str]]:
    """Only statically knowable dict returns, including a direct helper return."""
    function = function or route.function
    seen = set() if seen is None else seen
    if function.name in seen:
        return []
    seen = seen | {function.name}
    nodes = []
    def visit(node):
        if node is not function and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            return
        nodes.append(node)
        for child in ast.iter_child_nodes(node):
            visit(child)
    visit(function)
    assigned = {target.id: node.value for node in nodes if isinstance(node, ast.Assign)
                for target in node.targets if isinstance(target, ast.Name) and isinstance(node.value, ast.Dict)}
    result = []
    for node in nodes:
        if not isinstance(node, ast.Return):
            continue
        value = assigned.get(node.value.id) if isinstance(node.value, ast.Name) else node.value
        if isinstance(value, ast.Dict) and all(isinstance(key, ast.Constant) and isinstance(key.value, str) for key in value.keys):
            result.append({key.value for key in value.keys})
        elif isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in route.functions:
            result.extend(success_keys(route, route.functions[value.func.id], seen))
    return result


def response_schema(spec_path: Path, schema: dict) -> dict:
    if "$ref" not in schema:
        return schema
    reference = schema["$ref"]
    # Keep all validation offline. No remote schema retrieval or filesystem escape.
    target = (spec_path.parent / reference).resolve()
    if not reference.startswith("./") or not target.is_relative_to(spec_path.parent.resolve()):
        raise ValueError(f"Unsupported nonlocal response schema reference: {reference}")
    return json.loads(target.read_text(encoding="utf-8"))


def reference_problems(value: Any, directory: Path) -> list[str]:
    problems = []
    if isinstance(value, dict):
        reference = value.get("$ref")
        if reference and not reference.startswith("#/"):
            if not reference.startswith("./") or not (directory / reference.split("#", 1)[0]).resolve().is_relative_to(directory.resolve()):
                problems.append(f"Nonlocal schema reference is forbidden in offline checks: {reference}")
        for item in value.values():
            problems.extend(reference_problems(item, directory))
    elif isinstance(value, list):
        for item in value:
            problems.extend(reference_problems(item, directory))
    return problems


def compare_operation(route: Route, operation: dict, spec: dict, spec_path: Path) -> list[str]:
    problems = []
    schemes = spec.get("components", {}).get("securitySchemes", {})
    alternatives = operation.get("security", spec.get("security"))
    headers, documented = declared_headers(route), set()
    if not alternatives or any(not alternative for alternative in alternatives):
        problems.append("internal operation must explicitly require service authentication")
    for alternative in alternatives or []:
        for name in alternative:
            scheme = schemes.get(name, {})
            if scheme.get("type") != "apiKey" or scheme.get("in") != "header":
                problems.append(f"unknown/non-header authentication scheme: {name}")
                continue
            header = scheme["name"].lower()
            documented.add(header)
            if header not in headers:
                problems.append(f"authentication header is not declared on this handler: {header}")
    if headers != documented:
        problems.append(f"handler/document authentication headers differ: {sorted(headers)} / {sorted(documented)}")
    path_names = set(re.findall(r"\{([^}]+)\}", route.path))
    parameters = {p["name"]: p for p in operation.get("parameters", []) if p.get("in") == "path"}
    if path_names != set(parameters):
        problems.append("path parameters do not match the route placeholders")
    for arg, _ in arguments(route.function):
        if arg.arg in parameters:
            expected = type_schema(arg.annotation)
            actual = parameters[arg.arg].get("schema", {})
            for name, value in expected.items():
                if actual.get(name) != value:
                    problems.append(f"path parameter {arg.arg}.{name} differs from provider")
    bodies = [route.models[arg.annotation.id] for arg, _ in arguments(route.function)
              if isinstance(arg.annotation, ast.Name) and arg.annotation.id in route.models]
    declared_body = operation.get("requestBody")
    if bool(bodies) != bool(declared_body):
        problems.append("request body declaration differs from provider")
    if bodies and declared_body:
        expected = model_schema(bodies[0])
        actual = declared_body.get("content", {}).get("application/json", {}).get("schema", {})
        if not declared_body.get("required"):
            problems.append("provider body is required")
        if set(expected["required"]) != set(actual.get("required", [])):
            problems.append(f"request required fields differ: expected {expected['required']}")
        if set(expected["properties"]) != set(actual.get("properties", {})):
            problems.append("request property names differ from provider model")
        for field, schema in expected["properties"].items():
            documented_field = actual.get("properties", {}).get(field, {})
            for name, value in schema.items():
                actual_value = documented_field.get(name)
                if name == "type":
                    value = set(value if isinstance(value, list) else [value])
                    actual_value = set(actual_value if isinstance(actual_value, list) else [actual_value])
                if actual_value != value:
                    problems.append(f"request {field}.{name} differs from provider model")
    schema = operation.get("responses", {}).get("200", {}).get("content", {}).get("application/json", {}).get("schema", {})
    schema = response_schema(spec_path, schema)
    required = set(schema.get("required", []))
    for returned in success_keys(route):
        if required - returned:
            problems.append(f"success response requires fields provider does not always return: {sorted(required - returned)}")
    return problems


def check(root: Path = ROOT) -> list[str]:
    routes, problems = provider_routes(root)
    covered, identifiers = set(), {}
    for path in sorted((root / "contracts").glob("*-api.yaml")):
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        issues = reference_problems(spec, path.parent)
        if issues:
            problems.extend(issues)
            continue
        try:
            OpenAPIV31SpecValidator(spec, base_uri=path.as_uri()).validate()
        except Exception as error:
            problems.append(f"{path.name}: invalid OpenAPI: {error}")
            continue
        for endpoint, methods in spec.get("paths", {}).items():
            for method, operation in methods.items():
                if method not in METHODS:
                    continue
                key = method, endpoint
                covered.add(key)
                identifier = operation.get("operationId")
                if not identifier:
                    problems.append(f"{path.name}: {key}: missing operationId")
                elif identifier in identifiers and identifiers[identifier] != key:
                    problems.append(f"operationId collision: {identifier}")
                else:
                    identifiers[identifier] = key
                # Teacher Next.js handlers are checked separately using TypeScript AST.
                if path.name == "teacher-service-api.yaml":
                    continue
                if key not in routes:
                    problems.append(f"{path.name}: provider has no {method.upper()} {endpoint}")
                    continue
                try:
                    issues = compare_operation(routes[key], operation, spec, path)
                except (ValueError, KeyError) as error:
                    issues = [str(error)]
                problems.extend(f"{path.name}: {method.upper()} {endpoint}: {issue}" for issue in issues)
    problems.extend(f"Undocumented provider operation: {method.upper()} {endpoint}" for method, endpoint in sorted(set(routes) - covered))
    schema_path = root / "contracts/learning-context.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    issues = reference_problems(schema, schema_path.parent)
    if issues:
        return problems + issues
    Draft202012Validator.check_schema(schema)
    fixture_path = root / "contracts/fixtures/platform-learning-context-v1.json"
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for error in validator.iter_errors(json.loads(fixture_path.read_text(encoding="utf-8"))):
        problems.append(f"Legacy learning-context fixture: {error.json_path}: {error.message}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    problems = check(args.root.resolve())
    if problems:
        for problem in problems:
            print(f"[ERROR] {problem}")
        return 1
    print("[OK] OpenAPI, provider methods/headers/body declarations, known response keys and legacy context fixture")
    print("No application imports, credentials, database access, HTTP requests or runtime switches.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
