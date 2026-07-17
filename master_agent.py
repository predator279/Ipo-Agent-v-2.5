# master_agent.py (Upgraded with Conversational Memory)

import os
import json
from langchain_classic.agents import AgentExecutor
from langchain_classic.agents import create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.tools import tool
from agents.tools import get_llm
from sentiment_agent import analyze_sentiment
from chatbot_agent import process_and_store_document, create_rag_chain


# --- Tool Definitions (No Changes) ---
@tool
def rhp_document_qa(query: str) -> str:
    """..."""
    return "RAG chain not initialized."


@tool
def market_sentiment_analyzer(query: str) -> str:
    """..."""
    ipo_name = query
    result = analyze_sentiment(ipo_name)
    if 'error' in result:
        return result['error']
    return json.dumps(result, indent=2)


# --- create_master_agent function (UPGRADED FOR HISTORY) ---
def create_master_agent(rag_chain, ipo_name: str):
    """
    Creates the master agent with conversational memory.
    """
    # --- THIS IS THE CRITICAL FIX SECTION ---
    # 1. Connect the RAG chain, expecting the 'query' from the agent
    rhp_document_qa.func = lambda query: rag_chain.invoke(query)

    # 2. Connect the sentiment analyzer, IGNORING the agent's query
    #    and using the correct ipo_name instead.
    market_sentiment_analyzer.func = lambda query: analyze_sentiment(ipo_name)
    # ----------------------------------------

    tools = [rhp_document_qa, market_sentiment_analyzer]
    llm = get_llm(model_name="llama-3.3-70b-versatile", temperature=0)

    # UPGRADED PROMPT WITH MEMORY (This part is perfect)
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system",
             f"You are a master financial assistant analyzing the '{ipo_name}' IPO. "
             "You have two specialist tools. Your main job is to route the user's question to the correct tool. "
             "1. `rhp_document_qa`: Use for factual questions about the company from its official document. "
             "2. `market_sentiment_analyzer`: Use for questions about public opinion, hype, or 'GMP'. "
             "The user's direct question should be the input for `rhp_document_qa`. The `market_sentiment_analyzer` tool does not need specific input from the user's question. "
             "If the user asks for a broad 'summary' or 'analysis', you should first use the `rhp_document_qa` tool, "
             "and then use the `market_sentiment_analyzer` tool to provide a complete picture."
             ),
            MessagesPlaceholder(variable_name="chat_history"),
            ("user", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ]
    )

    agent = create_tool_calling_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True, handle_parsing_errors=True)
    return agent_executor


if __name__ == "__main__":
    # ... (no changes to the main loop)
    print("--- IPO Analysis Master Agent ---")
    ipo_to_analyze = input("Enter the name of the IPO you want to analyze (e.g., 'Tata Technologies'): ")
    vectorstore = process_and_store_document(ipo_to_analyze)
    if vectorstore:
        rag_chain = create_rag_chain(vectorstore)
        master_agent = create_master_agent(rag_chain, ipo_to_analyze)
        print("\n✅ Master agent is ready...")
        while True:
            user_question = input("Your Question: ")
            if user_question.lower() == 'exit':
                break
            result = master_agent.invoke({"input": user_question})
            print("\n--- Answer ---\n")
            print(result["output"])
            print("\n--------------\n")