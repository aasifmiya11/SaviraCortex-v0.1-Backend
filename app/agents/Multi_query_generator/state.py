from typing import TypedDict

from langchain_core.messages import BaseMessage, HumanMessage


class MultiQueryGeneratorState(TypedDict):
    current_query: str
    conversation_history: list[BaseMessage]
    generated_queries: list[HumanMessage]