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
from prompts import QUERY_REPHRASE_TEMPLATE, QUERY_ANSWER_TEMPLATE, SYSTEM_PROMPT
from haystack.components.converters import OutputAdapter
from haystack_integrations.components.retrievers.pinecone import PineconeEmbeddingRetriever
from haystack import Pipeline
from haystack.dataclasses import Document

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if not load_dotenv():
    logger.error("No .env file found")


# --- Helper Functions (from your notebook) ---
def create_docstore() -> PineconeDocumentStore:
    return PineconeDocumentStore(
        api_key=Secret.from_env_var("PINECONE_API_KEY"),
        index="archiefutrecht",  # is nu statisch, raad aan gewoon in .env te zetten
        dimension=1536,  # text-embedding-3-small
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

def create_qa_pipeline() -> Pipeline:
    pipeline = Pipeline()

    query_rephrase_builder = PromptBuilder(template=QUERY_REPHRASE_TEMPLATE)
    answer_builder = PromptBuilder(template=QUERY_ANSWER_TEMPLATE)

    rephrase_llm = OpenAIGenerator()
    answer_llm = OpenAIGenerator(system_prompt=SYSTEM_PROMPT)

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


# --- Streamlit App ---
st.title("Document Chatbot")

# Initialize chat history in session state if it doesn't exist
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat messages from history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if "sources" in message:
            with st.expander("Sources"):
                for source in message["sources"]:
                    st.markdown(f"- `{source}`")
                if "image_paths" in message:
                    for image_path in message["image_paths"]:
                        st.image(image_path)

                if "archive_numbers" in message:
                    st.markdown("Archive Numbers:")
                    for archive_number in message["archive_numbers"]:
                        st.markdown(f"- {archive_number}")



# User Input & Query Logic
if query := st.chat_input("Ask a question about the documents"):
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": query})
    with st.chat_message("user"):
        st.markdown(query)

    # Get the response from the pipeline
    try:
        pipeline = create_qa_pipeline()
        response = pipeline.run(data={"query_rephrase_builder": {"query": query}}, include_outputs_from=["pinecone_retriever"])
        bot_response = response.get("answer_llm").get("replies")[0]
        source_documents = response.get("pinecone_retriever").get("documents")
        
        # Extract source file paths, image paths and archive numbers from Document objects
        source_paths = []
        image_paths = set()
        archive_numbers = set()
        for doc in source_documents:
            if isinstance(doc, Document):
                print(doc.meta)
                print("------------------------------------------------")
                image_paths.add(doc.meta.get("representatieve\nafbeelding", None))
                archive_numbers.add(doc.meta.get("invnr", "unknown")) # assuming your key for archive number is invnr
        
        # Filter out any None image paths
        image_paths = [path for path in image_paths if path is not None]


    except Exception as e:
        bot_response = f"An error occurred: {e}"
        source_paths = []  # Ensure source_paths is initialized even if there's an error
        image_paths = []
        archive_numbers = []


    # Add bot's response and sources to chat history
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": bot_response,
            "sources": source_paths,
            "image_paths": image_paths,
            "archive_numbers": archive_numbers
        }
    )

    # Display bot response in a chat message
    with st.chat_message("assistant"):
        st.markdown(bot_response)
        if source_paths:
            with st.expander("Sources"):
                for source in source_paths:
                    st.markdown(f"- `{source}`")
                if image_paths:
                    for image_path in image_paths:
                       st.image(image_path)

                if archive_numbers:
                     st.markdown("Archive Numbers:")
                     for archive_number in archive_numbers:
                        st.markdown(f"- {archive_number}")