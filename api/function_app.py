import azure.functions as func
import logging
import json
import os
os.environ["FASTEMBED_CACHE_PATH"] = "/tmp/fastembed_cache"
from supabase import create_client, Client

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

def get_supabase() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    return create_client(url, key)

@app.route(route="ipos")
def get_ipos(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request for IPOs.')
    try:
        sb = get_supabase()
        # Fetch cached IPO profiles
        response = sb.table("ipo_profiles").select("ipo_name, symbol, updated_at").execute()
        return func.HttpResponse(json.dumps(response.data), mimetype="application/json")
    except Exception as e:
        logging.error(f"Error fetching IPOs: {e}")
        return func.HttpResponse("Error fetching IPOs", status_code=500)

@app.route(route="ipos/{ipo_name}")
def get_ipo_profile(req: func.HttpRequest) -> func.HttpResponse:
    ipo_name = req.route_params.get('ipo_name')
    logging.info(f'Fetching profile for {ipo_name}')
    try:
        sb = get_supabase()
        response = sb.table("ipo_profiles").select("profile_json").eq("ipo_name", ipo_name).execute()
        if response.data:
            return func.HttpResponse(json.dumps(response.data[0]['profile_json']), mimetype="application/json")
        else:
            return func.HttpResponse("Not Found", status_code=404)
    except Exception as e:
        logging.error(f"Error fetching IPO profile: {e}")
        return func.HttpResponse("Error", status_code=500)


def _safe_name(ipo_name: str) -> str:
    return "".join(c for c in ipo_name if c.isalnum() or c in " -_").rstrip()

def get_rag_chain(ipo_name: str):
    from langchain_qdrant import QdrantVectorStore
    from qdrant_client import QdrantClient
    from langchain_community.embeddings.fastembed import FastEmbedEmbeddings
    from langchain_classic.chains import create_history_aware_retriever, create_retrieval_chain
    from langchain_classic.chains.combine_documents import create_stuff_documents_chain
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

    qdrant_url = os.environ.get("QDRANT_URL")
    qdrant_api_key = os.environ.get("QDRANT_API_KEY")
    
    # Init LLM (Try Groq, fallback to Gemini)
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        from langchain_groq import ChatGroq
        llm = ChatGroq(temperature=0, model_name="llama-3.3-70b-versatile", groq_api_key=groq_key)
    else:
        from langchain_google_genai import ChatGoogleGenerativeAI
        gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not gemini_key:
            raise ValueError("Missing LLM API Key: Please set GROQ_API_KEY or GEMINI_API_KEY in Azure App Settings (Environment Variables).")
        llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", temperature=0, api_key=gemini_key)

    # Init Vectorstore
    embeddings = FastEmbedEmbeddings(model_name="BAAI/bge-small-en-v1.5")
    client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
    vectorstore = QdrantVectorStore(
        client=client,
        collection_name=_safe_name(ipo_name),
        embedding=embeddings,
    )
    
    retriever = vectorstore.as_retriever(
        search_type="mmr",
        search_kwargs={"k": 8, "fetch_k": 24, "lambda_mult": 0.6},
    )

    contextualize_q_prompt = ChatPromptTemplate.from_messages([
        ("system", "Given the conversation history and a follow-up question, rewrite the question as a fully self-contained standalone question. Do NOT answer it. If the question is already standalone, return it unchanged."),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ])

    history_aware_retriever = create_history_aware_retriever(llm, retriever, contextualize_q_prompt)

    qa_system_prompt = """You are a senior financial analyst assistant specialising in Indian IPOs.
You answer questions using ONLY the excerpts from the company's Red Herring Prospectus (RHP) or DRHP provided below.

Guidelines:
- If a chunk is labelled [TABLE — page N], treat it as a markdown table and extract exact numbers.
- Cite the page number when quoting a figure (e.g. "Revenue was ₹120 Cr (page 312)").
- If multiple chunks contain conflicting numbers, state the discrepancy and cite both pages.
- If the information is genuinely not present in the provided excerpts, say so clearly.
  Do NOT invent numbers or draw on external knowledge.
- For financial metrics (revenue, PAT, EBITDA, margins), always include the fiscal year / period.
- Respond in clear, structured prose. Use bullet points for lists of risks or objects of issue.

CONTEXT FROM RHP:
{context}"""

    qa_prompt = ChatPromptTemplate.from_messages([
        ("system", qa_system_prompt),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ])

    question_answer_chain = create_stuff_documents_chain(llm, qa_prompt)
    return create_retrieval_chain(history_aware_retriever, question_answer_chain)


@app.route(route="chat", methods=["POST"])
def chat(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Processing chat request.')
    try:
        req_body = req.get_json()
        ipo_name = req_body.get('ipo_name')
        message = req_body.get('message')
        history_data = req_body.get('chat_history', [])
        
        if not ipo_name or not message:
            return func.HttpResponse("Missing ipo_name or message", status_code=400)
            
        from langchain_core.messages import AIMessage, HumanMessage
        chat_history = []
        for h in history_data:
            if h.get('role') == 'user':
                chat_history.append(HumanMessage(content=h.get('content')))
            else:
                chat_history.append(AIMessage(content=h.get('content')))
                
        rag_chain = get_rag_chain(ipo_name)
        result = rag_chain.invoke({"input": message, "chat_history": chat_history})
        
        return func.HttpResponse(json.dumps({"answer": result["answer"]}), mimetype="application/json")
    except Exception as e:
        logging.error(f"Error in chat endpoint: {e}")
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=500, mimetype="application/json")
