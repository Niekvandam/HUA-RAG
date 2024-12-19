import streamlit as st
from dotenv import load_dotenv
import logging
import os
import sys
from haystack_integrations.document_stores.pinecone import PineconeDocumentStore
from haystack.components.embedders import OpenAIDocumentEmbedder, OpenAITextEmbedder
from haystack.utils import Secret
from haystack.document_stores.types.policy import DuplicatePolicy
from haystack.components.writers import DocumentWriter
from haystack.components.builders import PromptBuilder
from haystack.components.generators import OpenAIGenerator
from prompts import QUERY_REPHRASE_TEMPLATE, QUERY_ANSWER_TEMPLATE, SYSTEM_PROMPT, SYSTEM_PROMPT_2
from haystack.components.converters import OutputAdapter
from haystack_integrations.components.retrievers.pinecone import PineconeEmbeddingRetriever
from haystack import Pipeline
from haystack.dataclasses import Document, StreamingChunk
from typing import List, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if not load_dotenv():
    logger.error("No .env file found")

def create_docstore() -> PineconeDocumentStore:
    return PineconeDocumentStore(
        api_key=Secret.from_env_var("PINECONE_API_KEY"),
        index="archiefutrecht",
        dimension=1536,
    )

def create_document_embedder() -> OpenAIDocumentEmbedder:
    return OpenAIDocumentEmbedder(
        model="text-embedding-3-small",
        api_key=Secret.from_env_var("OPENAI_API_KEY"),
    )

def create_text_embedder() -> OpenAITextEmbedder:
    return OpenAITextEmbedder(
        model="text-embedding-3-small",
        api_key=Secret.from_env_var("OPENAI_API_KEY"),
    )

def create_document_writer(docstore) -> DocumentWriter:
    return DocumentWriter(document_store=docstore, policy=DuplicatePolicy.OVERWRITE) 

def create_pinecone_retriever() -> PineconeEmbeddingRetriever:
    return PineconeEmbeddingRetriever(
        document_store=create_docstore()
    )

def create_llm_output_adapter() -> OutputAdapter:
    return OutputAdapter(
        template="{{ replies [0] }}",
        output_type=str
    )

def create_qa_pipeline(streaming_callback) -> Pipeline:
    pipeline = Pipeline()

    query_rephrase_builder = PromptBuilder(template=QUERY_REPHRASE_TEMPLATE)
    answer_builder = PromptBuilder(template=QUERY_ANSWER_TEMPLATE)
    answer_llm = OpenAIGenerator(system_prompt=SYSTEM_PROMPT_2, streaming_callback=streaming_callback)
    rephrase_llm = OpenAIGenerator()
    rephrase_output_adapter = create_llm_output_adapter()
    question_embedder = create_text_embedder()
    pinecone_retriever = create_pinecone_retriever()

    pipeline.add_component("query_rephrase_builder", query_rephrase_builder)
    pipeline.add_component("rephrase_output_adapter", rephrase_output_adapter)
    pipeline.add_component("answer_builder", answer_builder)
    pipeline.add_component("rephrase_llm", rephrase_llm)
    pipeline.add_component("answer_llm", answer_llm)
    pipeline.add_component("question_embedder", question_embedder)
    pipeline.add_component("pinecone_retriever", pinecone_retriever)

    pipeline.connect("query_rephrase_builder", "rephrase_llm")
    pipeline.connect("rephrase_llm", "rephrase_output_adapter")
    pipeline.connect("rephrase_output_adapter", "question_embedder")
    pipeline.connect("question_embedder.embedding", "pinecone_retriever.query_embedding")
    pipeline.connect("pinecone_retriever", "answer_builder")
    pipeline.connect("answer_builder", "answer_llm")

    return pipeline

st.title("Document Chatbot")

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

def create_streaming_callback(message_placeholder):
    full_response = ""
    image_paths: List[str] = []
    archive_numbers: List[str] = []

    def streaming_callback(chunk: StreamingChunk):
        nonlocal full_response, image_paths, archive_numbers
        full_response, image_paths, archive_numbers = process_streaming_response(
            [{'answer_llm': {'replies': [chunk.content]}, 'pinecone_retriever': {'documents': []}}],
            message_placeholder,
            full_response,
            image_paths,
            archive_numbers
        )
    
    def get_data() -> Tuple[str, List[str], List[str], List[str]]:
        return full_response, image_paths, archive_numbers
    
    return streaming_callback, get_data

def process_streaming_response(response_stream, message_placeholder, full_response, image_paths, archive_numbers):
    for output in response_stream:
        if "answer_llm" in output:
            bot_response = output["answer_llm"].get("replies")[0]
            full_response += bot_response
            message_placeholder.markdown(full_response)

        if "pinecone_retriever" in output:
            source_documents = output["pinecone_retriever"].get("documents", [])
            for doc in source_documents:
                if isinstance(doc, Document):
                    img_url = doc.meta.get("representatieve\nafbeelding", None)
                    inv_number = doc.meta.get("invnr", "unknown")

                    image_paths.append(img_url if img_url else None)
                    archive_numbers.append(inv_number)

    return full_response, image_paths, archive_numbers
from haystack.dataclasses import ChatMessage

def get_message_history():
    return st.session_state.messages

def get_haystack_chat_history():
    history = get_message_history()
    messages = []
    messages.append(ChatMessage.from_system(SYSTEM_PROMPT_2))
    for message in history:
        print(history)
        if message.get("role") == "user":
            messages.append(ChatMessage.from_user(message.get("content")))
        elif message.get("role") == "assistant":
            messages.append(ChatMessage.from_assistant(message.get("content")))
    return messages
            

# Layout: left column for chat, right column for sources
col1, _ = st.columns([3, 1])


# Display chat messages from history in the left column
with col1:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

# User query
query = st.chat_input("Ask a question about the documents")

if query:
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": query})

    # Clear the sidebar for new response
    st.sidebar.empty()

    # Show user's query in chat
    with col1:
        with st.chat_message("user"):
            st.markdown(query)

    # Prepare streaming callback
    with col1:
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            streaming_callback, get_data = create_streaming_callback(message_placeholder)
            
            pipeline = create_qa_pipeline(streaming_callback)
            try:
                history = get_haystack_chat_history()
                print(history)
                response = pipeline.run(
                    data={"query_rephrase_builder": {"query": query, "history": history}, "answer_builder": {"history": history}},
                    include_outputs_from=["pinecone_retriever", "query_rephrase_builder"],
                )
                print(response.get("query_rephrase_builder"))

                full_response, image_paths, archive_numbers = process_streaming_response(
                    [{
                        'answer_llm': {'replies': [response["answer_llm"]["replies"][0]]}, 
                        'pinecone_retriever': {'documents': response["pinecone_retriever"]["documents"]}
                    }],
                    message_placeholder, "", [], []
                )

            except Exception as e:
                full_response = f"An error occurred: {e}"
                image_paths = []
                archive_numbers = []
                st.markdown(full_response)

    # Store assistant message with sources in session state
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": full_response,
            "image_paths": image_paths,
            "archive_numbers": archive_numbers
        }
    )

    # Now display the sources for this assistant message in the sidebar
    if archive_numbers:
        st.sidebar.markdown("### Sources")
        for i, source in enumerate(archive_numbers):
            st.sidebar.write(f"**Invnr:** {archive_numbers[i]}")
            if image_paths[i]:
                st.sidebar.image(image_paths[i], use_container_width=True)
            # Optional: Add a horizontal divider for clarity
            if i < len(archive_numbers) - 1:
                st.sidebar.markdown("---")