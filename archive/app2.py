# app.py

import streamlit as st
import os
from langchain_core.messages import AIMessage, HumanMessage
# Import our new IPO fetcher
from ipo_fetcher import fetch_all_ipos
# Import the functions from your existing chatbot_agent.py
from chatbot_agent import process_and_store_document, create_rag_chain

# --- Page Configuration ---
st.set_page_config(
    page_title="IPO Analysis Chatbot",
    page_icon="🤖",
    layout="wide"
)

# --- API Key Configuration ---
# Set the API key from Streamlit's secrets
try:
    os.environ["GROQ_API_KEY"] = st.secrets["GROQ_API_KEY"]
except st.errors.SecretStorageKeyError:
    st.error("GROQ_API_KEY not found in Streamlit secrets. Please add it to your .streamlit/secrets.toml file.")
    st.stop()

# --- App Title ---
st.title("📄 IPO Analysis Chatbot")
st.caption("Powered by LangChain & Groq Llama3")

# --- Session State Initialization ---
if "messages" not in st.session_state:
    st.session_state.messages = []
if "qa_chain" not in st.session_state:
    st.session_state.qa_chain = None
if "ipo_name" not in st.session_state:
    st.session_state.ipo_name = ""

# --- Sidebar for IPO Selection ---
with st.sidebar:
    st.header("Select an IPO")

    # Fetch the list of all IPOs
    try:
        ipo_list = fetch_all_ipos()
        # Add a placeholder at the top for manual input
        options = ["--- Type IPO name manually ---"] + ipo_list
    except Exception as e:
        st.error("Failed to load IPO list.")
        options = ["--- Type IPO name manually ---"]

    # Create the dropdown (selectbox)
    selected_option = st.selectbox("Choose from available IPOs:", options)

    # A variable to hold the final IPO name to be processed
    ipo_to_process = ""

    if selected_option == "--- Type IPO name manually ---":
        # If manual is chosen, show a text input field
        manual_ipo_name = st.text_input("Enter the full name of the IPO:", placeholder="e.g., Tata Technologies")
        ipo_to_process = manual_ipo_name
    else:
        # Otherwise, use the selection from the dropdown
        ipo_to_process = selected_option
        st.write(f"You selected: **{ipo_to_process}**")

    if st.button("Load and Analyze IPO"):
        if ipo_to_process:
            # Create a placeholder for the progress bar right before the heavy lifting
            progress_bar = st.progress(0, text="Starting analysis...")
            with st.spinner(f"Processing document for {ipo_to_process}... This may take a moment."):
                st.session_state.ipo_name = ipo_to_process
                st.session_state.messages = []

                # vectorstore = process_and_store_document(st.session_state.ipo_name, progress_bar)
                # Pass the progress bar object to our updated function
                vectorstore = process_and_store_document(st.session_state.ipo_name, progress_bar)
                if vectorstore:
                    # Update the progress bar as we move to the next step
                    progress_bar.progress(0.9, text="Creating chat chain...")

                    st.session_state.qa_chain = create_rag_chain(vectorstore)

                    # Finish the progress bar and show success
                    progress_bar.progress(1.0, text=f"Analysis of {st.session_state.ipo_name} complete!")

                    st.success(f"Successfully loaded and analyzed {st.session_state.ipo_name}!")
                else:
                    progress_bar.empty()  # Clear the progress bar on failure
                    st.error(
                        f"Failed to process the document for {st.session_state.ipo_name}. The document may not be available.")
                    st.session_state.ipo_name = ""
        else:
            st.warning("Please select or enter an IPO name first.")

    st.info("Choose an IPO from the dropdown or select the manual option to type a name, then click 'Load'.")

# --- Main Chat Interface ---
# (The rest of this file remains exactly the same as before)
if st.session_state.ipo_name:
    st.info(f"Currently analyzing: **{st.session_state.ipo_name}**")

# Display existing chat messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Chat input for user's question
if prompt := st.chat_input("Ask a question about the RHP/DRHP..."):
    if not st.session_state.qa_chain:
        st.warning("Please load an IPO using the sidebar first.", icon="⚠️")
    else:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.spinner("Thinking..."):
            # --- THIS IS THE NEW LOGIC ---
            # Format the chat history for the LangChain model
            formatted_history = []
            for msg in st.session_state.messages[:-1]:  # Exclude the current question
                if msg["role"] == "user":
                    formatted_history.append(HumanMessage(content=msg["content"]))
                else:
                    formatted_history.append(AIMessage(content=msg["content"]))

            # Invoke the RAG chain with the new, required input format
            response_dict = st.session_state.qa_chain.invoke(
                {"input": prompt, "chat_history": formatted_history}
            )

            # The answer is now in a dictionary under the 'answer' key
            response = response_dict["answer"]
            # ---------------------------

            # Add AI response to session state and display it
            st.session_state.messages.append({"role": "assistant", "content": response})

            with st.chat_message("assistant"):
                st.markdown(response)
else:
    if not st.session_state.ipo_name:
        st.info("Welcome! Please select an IPO from the sidebar to start the analysis.")