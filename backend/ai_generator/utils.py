from django.conf import settings
import json
from utils.gemini_client import get_gemini_client, _get_llm_model_name # Centralized Gemini client
import google.api_core.exceptions

class GeminiQuotaExhaustedError(Exception):
    """Exception raised when Gemini API quota is exhausted."""
    pass


def get_gemini_response(user_message, document_context=""):
    """
    Generates an AI response using the Gemini API based on the user message and document context.
    Returns the raw text response from the AI.
    """
    gemini_client_instance = get_gemini_client()

    system_instruction_text = """You are a helpful legal assistant. Your goal is to help the user create a legal document.
- First, ask follow-up questions to gather all the necessary details.
- When you have enough information, generate the full legal document.
- The document **must** be in well-structured **Markdown format**. This includes:
    - **Document Title:** The main title of the document (`# Document Title`) should be at the very top, centered implicitly by markdown rendering, and clearly state the document's purpose.
    - **Headings:** Use clear and hierarchical headings (`#`, `##`, `###`) for sections and sub-sections.
    - **Lists:** Use unordered (`*` or `-`) and ordered (`1.`) lists where appropriate.
    - **Emphasis:** Use bold (`**text**`) for important terms and italics (`*text*`) for emphasis.
    - **Section Separation:** Use two newlines between sections to ensure clear visual separation.
    - **Placeholders:** For any information not provided by the user, use clear, descriptive placeholders in `[CAPITALIZED_SNAKE_CASE]` format (e.g., `[PARTY 1 NAME]`, `[EFFECTIVE DATE]`, `[AMOUNT IN WORDS]`).
- When you are ready to generate the document, just provide the full Markdown content of the document. Do not wrap it in JSON.
- If the user asks to update some information, you must look for the previous document you generated in the conversation history. You will use that document as the basis for your new version.
- You must then regenerate the **entire** document, incorporating the user's requested changes, and provide the full updated Markdown. Do not just provide the updated line or a confirmation message.
- **Signature Handling:** If the user uploads a signature, you will see a system message like `(System: The user has uploaded a signature...)` with a URL. When you generate the document, you **must** include this signature at the appropriate signature lines using the provided URL in the correct markdown format: `![Signature]({signature_url})`. **Do NOT acknowledge the system message about the signature upload in your conversational response.**
"""
    
    full_user_message = user_message
    if document_context:
        full_user_message = f"Please revise the following document based on the user's request.\n\nDocument to revise:\n```markdown\n{document_context}\n```\n\nUser request: {user_message}"

    gemini_conversation_history = [
        {"role": "user", "parts": [{"text": system_instruction_text + "\n\n" + full_user_message}]}
    ]

    # Call Gemini API
    try:
        chat_completion = gemini_client_instance.GenerativeModel(_get_llm_model_name()).generate_content(
            gemini_conversation_history,
            generation_config=gemini_client_instance.types.GenerationConfig(
                temperature=0.7,
                max_output_tokens=2000,
            ),
            safety_settings=[
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            ]
        )
        response_text = chat_completion.candidates[0].content.parts[0].text
        return response_text
    except google.api_core.exceptions.ResourceExhausted as e:
        error_message = f"Quota exceeded for Gemini API. Please try again later. Details: {e}"
        print(f"ERROR: {error_message}")
        raise GeminiQuotaExhaustedError("Quota exceeded for Gemini API. Please try again later.")


def get_gemini_response_stream(user_message, document_context=""):
    """
    Generates an AI response using the Gemini API based on the user message and document context.
    Yields chunks of text response from the AI.
    """
    gemini_client_instance = get_gemini_client()

    system_instruction_text = """You are a helpful legal assistant. Your goal is to help the user create a legal document.
- First, ask follow-up questions to gather all the necessary details.
- When you have enough information, generate the full legal document.
- The document **must** be in well-structured **Markdown format**. This includes:
    - **Document Title:** The main title of the document (`# Document Title`) should be at the very top, centered implicitly by markdown rendering, and clearly state the document's purpose.
    - **Headings:** Use clear and hierarchical headings (`#`, `##`, `###`) for sections and sub-sections.
    - **Lists:** Use unordered (`*` or `-`) and ordered (`1.`) lists where appropriate.
    - **Emphasis:** Use bold (`**text**`) for important terms and italics (`*text*`) for emphasis.
    - **Section Separation:** Use two newlines between sections to ensure clear visual separation.
    - **Placeholders:** For any information not provided by the user, use clear, descriptive placeholders in `[CAPITALIZED_SNAKE_CASE]` format (e.g., `[PARTY 1 NAME]`, `[EFFECTIVE DATE]`, `[AMOUNT IN WORDS]`).
- When you are ready to generate the document, just provide the full Markdown content of the document. Do not wrap it in JSON.
- If the user asks to update some information, you must look for the previous document you generated in the conversation history. You will use that document as the basis for your new version.
- You must then regenerate the **entire** document, incorporating the user's requested changes, and provide the full updated Markdown. Do not just provide the updated line or a confirmation message.
- **Signature Handling:** If the user uploads a signature, you will see a system message like `(System: The user has uploaded a signature...)` with a URL. When you generate the document, you **must** include this signature at the appropriate signature lines using the provided URL in the correct markdown format: `![Signature]({signature_url})`. **Do NOT acknowledge the system message about the signature upload in your conversational response.**
"""
    
    # Construct the conversation history for Gemini
    full_user_message = user_message
    if document_context:
        full_user_message = f"Please revise the following document based on the user's request.\n\nDocument to revise:\n```markdown\n{document_context}\n```\n\nUser request: {user_message}"

    gemini_conversation_history = [
        {"role": "user", "parts": [{"text": system_instruction_text + "\n\n" + full_user_message}]}
    ]

    # Call Gemini API with streaming
    try:
        response = gemini_client_instance.GenerativeModel(_get_llm_model_name()).generate_content(
            gemini_conversation_history,
            generation_config=gemini_client_instance.types.GenerationConfig(
                temperature=0.7,
                max_output_tokens=2000,
            ),
            safety_settings=[
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            ],
            stream=True
        )
        
        for chunk in response:
            if chunk.text:
                yield chunk.text

    except google.api_core.exceptions.ResourceExhausted as e:
        error_message = f"Quota exceeded for Gemini API. Please try again later. Details: {e}"
        print(f"ERROR: {error_message}")
        yield json.dumps({
            "type": "error",
            "text": "I'm sorry, I've hit my daily limit for generating content. Please try again after some time."
        })
    except Exception as e:
        error_message = f"An unexpected error occurred with the Gemini API: {e}"
        print(f"ERROR: {error_message}")
        yield json.dumps({
            "type": "error",
            "text": "An unexpected error occurred while communicating with the AI. Please try again."
        })