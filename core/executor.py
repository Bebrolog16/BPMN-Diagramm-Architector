import ast
import os

from core.diagram import DiagramSDK
from core.exporter import BPMNExporter
from core.layout import LayoutEngine


class _BoundExporter:
    """Exporter adapter that pins all writes to the configured output file."""

    def __init__(self, graph, output_path):
        self.exporter = BPMNExporter(graph)
        self.output_path = output_path

    def export(self, _requested_path=None):
        return self.exporter.export(self.output_path)


class _GeneratedCodeInterpreter:
    """Evaluate the small declarative Python subset described in the system prompt."""

    MAX_SOURCE_CHARS = 50_000
    MAX_AST_NODES = 5_000
    MAX_STATEMENTS = 500
    MAX_CONTAINER_ITEMS = 500

    METHODS = {
        DiagramSDK: {
            "add_pool", "add_task", "add_user_task", "add_script_task",
            "add_exclusive_gateway", "add_parallel_gateway", "add_inclusive_gateway",
            "add_start_event", "add_end_event", "add_link", "add_subprocess", "add_group",
        },
        LayoutEngine: {"calculate_layout"},
        _BoundExporter: {"export"},
    }

    def __init__(self, output_path):
        self.output_path = output_path
        self.environment = {}
        self.layout_ran = False
        self.export_ran = False

    def run(self, source):
        try:
            if len(source) > self.MAX_SOURCE_CHARS:
                raise ValueError("Generated code is too large")
            tree = ast.parse(source, mode="exec")
            if sum(1 for _ in ast.walk(tree)) > self.MAX_AST_NODES:
                raise ValueError("Generated code has too many syntax nodes")
            if len(tree.body) > self.MAX_STATEMENTS:
                raise ValueError("Generated code has too many statements")
            for statement in tree.body:
                self._statement(statement)
            if not any(isinstance(value, DiagramSDK) for value in self.environment.values()):
                raise ValueError("Generated code must initialize sdk = DiagramSDK()")
            if not self.layout_ran:
                raise ValueError("Generated code must calculate the diagram layout")
            if not self.export_ran or not os.path.isfile(self.output_path):
                raise ValueError("Generated code did not export a BPMN file")
        except (SyntaxError, TypeError, ValueError, KeyError, AttributeError) as exc:
            raise ValueError(f"Rejected generated code: {exc}") from exc

    def _statement(self, statement):
        if isinstance(statement, ast.Assign):
            value = self._expression(statement.value)
            for target in statement.targets:
                self._assign(target, value)
            return
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            self._expression(statement.value)
            return
        raise ValueError(f"Unsupported statement: {type(statement).__name__}")

    def _assign(self, target, value):
        if isinstance(target, ast.Name):
            self.environment[target.id] = value
            return
        if isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (tuple, list)):
            if len(target.elts) != len(value):
                raise ValueError("Tuple assignment does not match returned values")
            for child, child_value in zip(target.elts, value):
                self._assign(child, child_value)
            return
        raise ValueError("Only simple variable assignment is allowed")

    def _expression(self, expression):
        if isinstance(expression, ast.Constant):
            if isinstance(expression.value, (str, int, float, bool, type(None))):
                return expression.value
            raise ValueError("Unsupported literal")
        if isinstance(expression, ast.Name):
            if expression.id not in self.environment:
                raise ValueError(f"Unknown variable: {expression.id}")
            return self.environment[expression.id]
        if isinstance(expression, ast.List):
            if len(expression.elts) > self.MAX_CONTAINER_ITEMS:
                raise ValueError("Generated list is too large")
            return [self._expression(item) for item in expression.elts]
        if isinstance(expression, ast.Tuple):
            if len(expression.elts) > self.MAX_CONTAINER_ITEMS:
                raise ValueError("Generated tuple is too large")
            return tuple(self._expression(item) for item in expression.elts)
        if isinstance(expression, ast.Subscript):
            sequence = self._expression(expression.value)
            if not isinstance(sequence, (list, tuple)):
                raise ValueError("Indexing is allowed only for lists and tuples")
            if not isinstance(expression.slice, ast.Constant) or not isinstance(expression.slice.value, int):
                raise ValueError("List and tuple indexes must be integer literals")
            try:
                return sequence[expression.slice.value]
            except IndexError as exc:
                raise ValueError("List or tuple index is out of range") from exc
        if isinstance(expression, ast.Attribute):
            if isinstance(expression.value, ast.Name):
                instance = self._expression(expression.value)
                if isinstance(instance, DiagramSDK) and expression.attr in {
                    "graph", "ROOT_PROCESS_ID", "ROOT_START_TASK_ID", "ROOT_END_TASK_ID"
                }:
                    return getattr(instance, expression.attr)
            raise ValueError("Attribute access is not allowed")
        if isinstance(expression, ast.Call):
            return self._call(expression)
        raise ValueError(f"Unsupported expression: {type(expression).__name__}")

    def _call(self, expression):
        if isinstance(expression.func, ast.Name):
            if expression.func.id == "DiagramSDK":
                if expression.args or expression.keywords:
                    raise ValueError("DiagramSDK takes no arguments")
                return DiagramSDK()
            if expression.func.id == "LayoutEngine":
                args, kwargs = self._arguments(expression)
                if len(args) != 1 or kwargs:
                    raise ValueError("LayoutEngine requires only sdk.graph")
                return LayoutEngine(args[0])
            if expression.func.id == "BPMNExporter":
                args, kwargs = self._arguments(expression)
                if len(args) != 1 or kwargs:
                    raise ValueError("BPMNExporter requires only sdk.graph")
                return _BoundExporter(args[0], self.output_path)
            raise ValueError(f"Function calls are not allowed: {expression.func.id}")

        if not isinstance(expression.func, ast.Attribute) or not isinstance(expression.func.value, ast.Name):
            raise ValueError("Only direct SDK method calls are allowed")
        instance = self._expression(expression.func.value)
        method_name = expression.func.attr
        allowed = self.METHODS.get(type(instance), set())
        if method_name not in allowed:
            raise ValueError(f"SDK method is not allowed: {method_name}")
        method = getattr(instance, method_name)
        args, kwargs = self._arguments(expression)
        result = method(*args, **kwargs)
        if isinstance(instance, LayoutEngine) and method_name == "calculate_layout":
            self.layout_ran = True
        if isinstance(instance, _BoundExporter) and method_name == "export":
            self.export_ran = True
        return result

    def _arguments(self, call):
        if any(isinstance(arg, ast.Starred) for arg in call.args):
            raise ValueError("Starred arguments are not allowed")
        args = [self._expression(arg) for arg in call.args]
        kwargs = {}
        for keyword in call.keywords:
            if keyword.arg is None or keyword.arg in kwargs:
                raise ValueError("Expanded or duplicate keyword arguments are not allowed")
            kwargs[keyword.arg] = self._expression(keyword.value)
        return args, kwargs


class CodeExecutor:
    """Run only the constrained SDK language emitted by the model."""

    def __init__(self, output_filename="result.bpmn"):
        self.output_filename = os.path.abspath(output_filename)

    def execute(self, code: str):
        try:
            if not isinstance(code, str) or not code.strip():
                raise ValueError("Generated code is empty")
            os.makedirs(os.path.dirname(self.output_filename), exist_ok=True)
            interpreter = _GeneratedCodeInterpreter(self.output_filename)
            interpreter.run(code)
            return {"success": True, "output": self.output_filename, "error": None}
        except Exception as exc:
            return {"success": False, "output": None, "error": str(exc)}
