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
from haystack import Pipeline, component
from haystack.dataclasses import Document, StreamingChunk
from typing import List, Set, Tuple, Dict, Any
from openai import OpenAI, Stream
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from typing import Callable, Union, Optional
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

    answer_llm = CustomOpenAIGenerator(system_prompt=SYSTEM_PROMPT) # added streaming callback here
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

# --- Custom OpenAIGenerator Class ---
@component
class CustomOpenAIGenerator(OpenAIGenerator):
    """
    Extends the OpenAIGenerator class to allow streaming with a callback at the run method.
    """
    def __init__(  # pylint: disable=too-many-positional-arguments
        self,
        api_key: Secret = Secret.from_env_var("OPENAI_API_KEY"),
        model: str = "gpt-4o-mini",
        api_base_url: Optional[str] = None,
        organization: Optional[str] = None,
        system_prompt: Optional[str] = None,
        generation_kwargs: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ):
        super().__init__(
            api_key=api_key,
            model=model,
            streaming_callback=None,
            api_base_url=api_base_url,
            organization=organization,
            system_prompt=system_prompt,
            generation_kwargs=generation_kwargs,
            timeout=timeout,
            max_retries=max_retries,
        )
    @component.output_types(replies=List[str], meta=List[Dict[str, Any]])
    def run(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        streaming_callback: Optional[Callable[[StreamingChunk], None]] = None,
        generation_kwargs: Optional[Dict[str, Any]] = None,
    ):
        """
        Invoke the text generation inference based on the provided messages and generation parameters.

        :param prompt:
            The string prompt to use for text generation.
        :param system_prompt:
            The system prompt to use for text generation. If this run time system prompt is omitted, the system
            prompt, if defined at initialisation time, is used.
        :param streaming_callback:
            A callback function that is called when a new token is received from the stream.
        :param generation_kwargs:
            Additional keyword arguments for text generation. These parameters will potentially override the parameters
            passed in the `__init__` method. For more details on the parameters supported by the OpenAI API, refer to
            the OpenAI [documentation](https://platform.openai.com/docs/api-reference/chat/create).
        :returns:
            A list of strings containing the generated responses and a list of dictionaries containing the metadata
        for each response.
        """
        message = ChatMessage.from_user(prompt)
        if system_prompt is not None:
            messages = [ChatMessage.from_system(system_prompt), message]
        elif self.system_prompt:
            messages = [ChatMessage.from_system(self.system_prompt), message]
        else:
            messages = [message]

        # update generation kwargs by merging with the generation kwargs passed to the run method
        generation_kwargs = {**self.generation_kwargs, **(generation_kwargs or {})}

        # adapt ChatMessage(s) to the format expected by the OpenAI API
        openai_formatted_messages = [_convert_message_to_openai_format(message) for message in messages]

        completion: Union[Stream[ChatCompletionChunk], ChatCompletion] = self.client.chat.completions.create(
            model=self.model,
            messages=openai_formatted_messages,  # type: ignore
            stream=streaming_callback is not None,
            **generation_kwargs,
        )

        completions: List[ChatMessage] = []
        if isinstance(completion, Stream):
            num_responses = generation_kwargs.pop("n", 1)
            if num_responses > 1:
                raise ValueError("Cannot stream multiple responses, please set n=1.")
            chunks: List[StreamingChunk] = []
            completion_chunk: Optional[ChatCompletionChunk] = None

            # pylint: disable=not-an-iterable
            for completion_chunk in completion:
                if completion_chunk.choices and streaming_callback:
                    chunk_delta: StreamingChunk = self._build_chunk(completion_chunk)
                    chunks.append(chunk_delta)
                    streaming_callback(chunk_delta)  # invoke callback with the chunk_delta
            # Makes type checkers happy
            assert completion_chunk is not None
            completions = [self._create_message_from_chunks(completion_chunk, chunks)]
        elif isinstance(completion, ChatCompletion):
            completions = [self._build_message(completion, choice) for choice in completion.choices]

        # before returning, do post-processing of the completions
        for response in completions:
            self._check_finish_reason(response)

        return {"replies": [message.text for message in completions], "meta": [message.meta for message in completions]}



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

def create_streaming_callback(message_placeholder):
    full_response = ""
    source_paths: List[str] = []
    image_paths: Set[str] = set()
    archive_numbers: Set[str] = set()

    def streaming_callback(chunk: StreamingChunk):
        nonlocal full_response, source_paths, image_paths, archive_numbers
        
        full_response, source_paths, image_paths, archive_numbers = process_streaming_response(
            [{'answer_llm': {'replies': [chunk.content]}, 'pinecone_retriever': {'documents': []}}],
            message_placeholder,
            full_response,
            source_paths,
            image_paths,
            archive_numbers
        )
    
    def get_data() -> Tuple[str, List[str], Set[str], Set[str]]:
      return full_response, source_paths, image_paths, archive_numbers
    
    return streaming_callback, get_data

def process_streaming_response(response_stream, message_placeholder, full_response, source_paths, image_paths, archive_numbers):
    for output in response_stream:
        if "answer_llm" in output:
            bot_response = output["answer_llm"].get("replies")[0]
            full_response += bot_response
            message_placeholder.markdown(full_response)

        if "pinecone_retriever" in output:
            source_documents = output["pinecone_retriever"].get("documents", [])

            for doc in source_documents:
                if isinstance(doc, Document):
                    image_paths.add(doc.meta.get("representatieve\nafbeelding", None))
                    archive_numbers.add(doc.meta.get("invnr", "unknown"))

            image_paths = [path for path in image_paths if path is not None]
            
            for doc in source_documents:
                if isinstance(doc, Document):
                    source_paths.append(doc.meta.get("file_path", "unknown"))
    return full_response, source_paths, image_paths, archive_numbers

# User Input & Query Logic
if query := st.chat_input("Ask a question about the documents"):
    # Clear the sidebar on new question
    st.sidebar.empty()

    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": query})
    with st.chat_message("user"):
        st.markdown(query)
    
    # Get the response from the pipeline in streaming mode
    try:
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            streaming_callback, get_data = create_streaming_callback(message_placeholder)
            
            pipeline = create_qa_pipeline()
            
            response = pipeline.run(
                data={"query_rephrase_builder": {"query": query}},
                include_outputs_from=["pinecone_retriever"],
                answer_llm = {"streaming_callback": streaming_callback}
            )
            
            full_response, source_paths, image_paths, archive_numbers = process_streaming_response(
                [{'answer_llm': {'replies': [response["answer_llm"]["replies"][0]]}, 'pinecone_retriever': {'documents': response["pinecone_retriever"]["documents"]}}], message_placeholder, "", [], set(), set())

            # Display the sidebar after the full response is received
            if full_response:
                if source_paths:
                    st.sidebar.markdown("**Sources:**")
                    for source in source_paths:
                        st.sidebar.markdown(f"- `{source}`")

                    if image_paths:
                        st.sidebar.markdown("**Images:**")
                        for image_path in image_paths:
                            st.sidebar.image(image_path)

                    if archive_numbers:
                        st.sidebar.markdown("**Archive Numbers:**")
                        for archive_number in archive_numbers:
                            st.sidebar.markdown(f"- {archive_number}")
        
    except Exception as e:
        full_response = f"An error occurred: {e}"
        source_paths = []
        image_paths = []
        archive_numbers = []
        with st.chat_message("assistant"):
            st.markdown(full_response)

    # Add bot's full response and sources to chat history
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": full_response,
            "sources": source_paths,
            "image_paths": list(image_paths),
            "archive_numbers": list(archive_numbers)
        }
    )