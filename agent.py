import os
import ast
import operator
from collections.abc import Iterator

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

load_dotenv()


model = ChatOpenAI(
    model_name=os.getenv("MODEL_NAME", "mistral.mistral-large-3-675b-instruct"),
    api_key=os.environ["MODEL_API_KEY"],
    base_url=os.getenv("MODEL_BASE_URL", "https://bedrock-mantle.us-east-1.api.aws/v1"),
)


_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}


def _calculate(node: ast.AST) -> int | float:
    if isinstance(node, ast.Expression):
        return _calculate(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _calculate(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        left = _calculate(node.left)
        right = _calculate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("exponent is too large")
        return _OPERATORS[type(node.op)](left, right)
    raise ValueError("only basic arithmetic is supported")


@tool
def calculator(expression: str) -> str:
    """Calculate a basic arithmetic expression, such as '(12 * 4) + 7'."""
    if len(expression) > 200:
        raise ValueError("expression is too long")
    try:
        result = _calculate(ast.parse(expression, mode="eval"))
    except (SyntaxError, TypeError, ValueError, ZeroDivisionError) as error:
        raise ValueError(f"invalid arithmetic expression: {error}") from error
    return str(result)


calculator_model = model.bind_tools([calculator])


def stream_agent_response(prompt: str) -> Iterator[str]:
    """Yield the agent response as it is generated."""
    messages = [HumanMessage(content=prompt)]
    while True:
        complete_message = None
        for chunk in calculator_model.stream(messages):
            complete_message = chunk if complete_message is None else complete_message + chunk
            content = getattr(chunk, "content", "")
            if isinstance(content, str) and content:
                yield content
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        yield item["text"]

        if not complete_message or not complete_message.tool_calls:
            return

        messages.append(complete_message)
        for tool_call in complete_message.tool_calls:
            if tool_call["name"] != "calculator":
                raise ValueError(f"unknown tool: {tool_call['name']}")
            result = calculator.invoke(tool_call["args"])
            messages.append(ToolMessage(content=result, tool_call_id=tool_call["id"]))