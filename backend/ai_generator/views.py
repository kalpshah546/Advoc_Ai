from rest_framework.decorators import api_view, parser_classes
from rest_framework.response import Response
from django.conf import settings
import json
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
import cloudinary.uploader

from .utils import get_gemini_response, GeminiQuotaExhaustedError # Import utility function and custom exception


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def chat(request):
    """
    API endpoint for the conversational legal document generator.
    """
    messages = request.data.get('messages', [])
    if not messages:
        return Response({'error': 'Messages are required'}, status=400)

    user_message = messages[-1]['text'] # Assuming the last message is the current user input
    document_context = "" # The chat view doesn't inherently have document context, it's built from messages

    try:
        signature_file = request.FILES.get('signature')
        if signature_file:
            try:
                upload_result = cloudinary.uploader.upload(signature_file)
                signature_url = upload_result['secure_url']
                # Append a system message to the user's message
                user_message += f"\n\n(System: The user has uploaded a signature. Please place it in the appropriate section of the document using the following markdown: ![Signature]({signature_url}))"
            except Exception as e:
                return Response({'error': f'Error uploading signature: {e}'}, status=500)

        response_text = get_gemini_response(user_message, document_context)

        print(f"Model response text: {response_text}")

        # The response from the model is just text, so we need to parse it to see
        # if it is a question or the final document.
        # For now, we will assume that if the response contains "```json", it is the final document in JSON format.
        # Otherwise, it is a question.
        if '```json' in response_text:
            # It's the final document
            # Extract the JSON part from the response
            json_str = response_text.split('```json')[1].split('```')[0]
            document_data = json.loads(json_str)
            return Response(document_data)
        else:
            # It's a question
            return Response({'type': 'question', 'text': response_text})

    except GeminiQuotaExhaustedError as e:
        print(f"Quota error in chat view: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        print(f"Error in chat view: {e}")
        print(f"Type of error: {type(e)}")
        return Response({'error': str(e)}, status=500)