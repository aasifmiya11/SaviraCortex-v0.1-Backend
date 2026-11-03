from typing import Sequence

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from app.llm.client import llm_client

from .config import MultiQueryGeneratorConfig
from .prompts import get_multi_query_generator_prompt
from .schemas import MultiQueryGeneratorOutput
from .state import MultiQueryGeneratorState


class MultiQueryGeneratorError(Exception):
    """Base exception for multi-query generation errors."""


class EmptyQueryError(MultiQueryGeneratorError):
    """Raised when the current query is empty."""


class MultiQueryGeneratorAgent:

    def __init__(
        self,
        config: MultiQueryGeneratorConfig | None = None,
        client=None,
        model=None,
    ):
        self.config = config or MultiQueryGeneratorConfig()

        self.client = client
        self.model = model

        if self.client is None:
            self.model = llm_client.get_llm()

        self.structured_llm = self.model.with_structured_output(
            MultiQueryGeneratorOutput
        )

        self.prompt = get_multi_query_generator_prompt(
            max_queries=self.config.max_queries
        )

        self.chain = self.prompt | self.structured_llm

        self.graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(MultiQueryGeneratorState)

        workflow.add_node(
            "generate_queries",
            self._generate_queries,
        )

        workflow.add_edge(START, "generate_queries")
        workflow.add_edge("generate_queries", END)

        return workflow.compile()

    def _generate_queries(
        self,
        state: MultiQueryGeneratorState,
    ) -> dict:

        current_query = state["current_query"].strip()

        if not current_query:
            raise EmptyQueryError("Current query cannot be empty.")

        conversation_history = state.get("conversation_history", [])

        result = self.chain.invoke(
            {
                "current_query": current_query,
                "conversation_history": conversation_history,
            },
            config={
                "metadata": {
                    "agent": "multi_query_generator",
                }
            },
        )

        queries = result.queries[:self.config.max_queries]

        generated_messages = [
            HumanMessage(content=query)
            for query in queries
        ]

        return {
            "generated_queries": generated_messages,
        }

    def generate(
        self,
        current_query: str,
        conversation_history: Sequence[BaseMessage] | None = None,
    ) -> list[HumanMessage]:

        if not current_query or not current_query.strip():
            raise EmptyQueryError("Current query cannot be empty.")

        history = list(conversation_history or [])

        result = self.graph.invoke(
            {
                "current_query": current_query,
                "conversation_history": history,
                "generated_queries": [],
            }
        )

        return result["generated_queries"]

    async def agenerate(
        self,
        current_query: str,
        conversation_history: Sequence[BaseMessage] | None = None,
    ) -> list[HumanMessage]:

        if not current_query or not current_query.strip():
            raise EmptyQueryError("Current query cannot be empty.")

        history = list(conversation_history or [])

        result = await self.graph.ainvoke(
            {
                "current_query": current_query,
                "conversation_history": history,
                "generated_queries": [],
            }
        )

        return result["generated_queries"]