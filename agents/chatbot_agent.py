# agents/chatbot_agent.py
import json
import time
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from mcp.tool_registry import MCPInvoiceTools
from config import settings
from utils.logger import setup_logger

logger = setup_logger("ChatbotAgent")

class ChatbotAgent:
    def __init__(self):
        """Initialize the dashboard chatbot, provider-agnostic LLM model, and tool bindings."""
        self.tool_wrapper = MCPInvoiceTools()
        self.tools = MCPInvoiceTools.get_registered_tools()
        self.tool_map = {tool.name: tool for tool in self.tools}
        self.api_key = settings.GROQ_API_KEY
        self.model_name = settings.GROQ_MODEL
        self.provider = settings.MODEL_PROVIDER
        
        self.llm = None
        self.llm_with_tools = None
        if self.api_key:
            try:
                self.llm = init_chat_model(
                    model=self.model_name,
                    model_provider=self.provider,
                    api_key=self.api_key,
                    temperature=0
                )
                self.llm_with_tools = self.llm.bind_tools(self.tools)
                logger.info(f"Initialized Chatbot LLM ({self.model_name}) with provider {self.provider} and bound tools.")
            except Exception as e:
                logger.warning(f"Could not initialize provider-agnostic Chatbot LLM: {e}")

    def converse(self, user_query: str) -> str:
        """
        Processes natural language queries and answers them using bound tool functions.
        """
        logger.info(f"Processing chatbot query: '{user_query}'")

        if self.llm_with_tools:
            try:
                messages = [
                    SystemMessage(content=(
                        "You are an AI assistant monitoring invoice status logs and metrics. "
                        "Use the available tools to retrieve system summaries, pending review queues, and rejection logs as needed. "
                        "Answer clearly, concisely, and professionally based on the retrieved data."
                    )),
                    HumanMessage(content=user_query)
                ]

                # First LLM invocation: may generate tool call requests
                ai_msg = self.llm_with_tools.invoke(messages)

                if hasattr(ai_msg, "tool_calls") and ai_msg.tool_calls:
                    logger.info(f"LLM generated {len(ai_msg.tool_calls)} tool call(s). Executing...")
                    messages.append(ai_msg)

                    for tool_call in ai_msg.tool_calls:
                        tool_name = tool_call["name"]
                        tool_args = tool_call.get("args", {})
                        if tool_name in self.tool_map:
                            tool_result = self.tool_map[tool_name].invoke(tool_args)
                            messages.append(ToolMessage(
                                content=json.dumps(tool_result),
                                tool_call_id=tool_call["id"]
                            ))

                    # Second LLM invocation: format the final tool results
                    final_response = self.llm.invoke(messages)
                    return final_response.content.strip()

                elif ai_msg.content:
                    return ai_msg.content.strip()

            except Exception as e:
                logger.error(f"Dynamic tool execution failed: {e}. Falling back to deterministic routing.")

        # Deterministic routing fallback if LLM call or binding fails
        query_lower = user_query.lower()
        if "review" in query_lower or "pending" in query_lower:
            results = self.tool_wrapper.fetch_pending_reviews()
            return f"I found {len(results)} invoices pending human review:\n{json.dumps(results, indent=2)}"
        elif "summary" in query_lower or "how many" in query_lower:
            summary = self.tool_wrapper.get_system_summary()
            return f"Here is the reconciliation summary:\n{json.dumps(summary, indent=2)}"
        elif "reject" in query_lower or "reason" in query_lower:
            rejections = self.tool_wrapper.query_rejections_by_reason()
            return f"Here are the details for rejected invoices:\n{json.dumps(rejections, indent=2)}"

        return "I can help you review system logs. Try asking: 'Show summary metrics' or 'Are there any invoices pending review?'"

    def converse_stream(self, user_query: str):
        """Streams chatbot response tokens for real-time UI rendering in Streamlit."""
        response_text = self.converse(user_query)
        words = response_text.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
            time.sleep(0.02)
