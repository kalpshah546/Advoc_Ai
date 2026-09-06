from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from mongoengine import DoesNotExist, errors
from authentication.models import User
from .models import LawyerProfile, LawyerConnectionRequest, Rating
from chat.models import ChatConversation, ChatMessage
import cloudinary
import cloudinary.uploader
from uuid import uuid4
from datetime import datetime
import random
import string

from .serializers import (
    LawyerProfileSerializer,
    LawyerConnectionRequestSerializer,
    LawyerConnectionStatusSerializer,
    RatingSerializer,
    RatingCreateSerializer,
)
from authentication.serializers import UserSerializer


def _generate_meet_link():
    """Generate a Google Meet-style link when a connection is accepted."""
    chars = string.ascii_lowercase
    part1 = ''.join(random.choices(chars, k=3))
    part2 = ''.join(random.choices(chars, k=4))
    part3 = ''.join(random.choices(chars, k=3))
    return f"https://meet.google.com/{part1}-{part2}-{part3}"


@api_view(['GET'])
@permission_classes([AllowAny])
def lawyer_list_view(request):
    """List approved lawyers with optional specialization filter and pagination"""
    # Self-healing: Remove broken profiles
    for p in LawyerProfile.objects():
        try:
            p.user
        except DoesNotExist:
            p.delete()

    specialization = request.query_params.get('specialization', '').strip()
    page = int(request.query_params.get('page', 1))
    page_size = int(request.query_params.get('page_size', 4))

    profiles = LawyerProfile.objects(verification_status='approved')
    
    if specialization:
        profiles = profiles.filter(specializations__icontains=specialization)
    
    total_count = profiles.count()
    skip = (page - 1) * page_size
    profiles = profiles.skip(skip).limit(page_size)
    
    valid_profiles = []
    for profile in profiles:
        try:
            # Check if the referenced user exists; this triggers the DB lookup
            if profile.user:
                valid_profiles.append(profile)
        except DoesNotExist:
            # Skip profiles with missing User references
            continue

    serializer = LawyerProfileSerializer(valid_profiles, many=True)
    return Response({
        'results': serializer.data,
        'has_more': (skip + page_size) < total_count,
        'total_count': total_count,
        'page': page
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def lawyer_detail_view(request, lawyer_id):
    """Retrieve lawyer detail"""
    try:
        user = User.objects(id=lawyer_id, role='lawyer').first()
    except DoesNotExist:
        user = None
    if not user:
        return Response({'error': 'Lawyer not found.'}, status=status.HTTP_404_NOT_FOUND)

    profile = LawyerProfile.objects(user=user).first()
    if not profile:
        return Response({'error': 'Lawyer profile not found.'}, status=status.HTTP_404_NOT_FOUND)

    serializer = LawyerProfileSerializer(profile)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def connect_with_lawyer_view(request, lawyer_id):
    """Create a connection request with a lawyer"""
    if str(request.user.id) == lawyer_id:
        return Response({'error': 'You cannot connect with yourself.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        lawyer = User.objects(id=lawyer_id, role='lawyer').first()
    except DoesNotExist:
        lawyer = None

    if not lawyer:
        return Response({'error': 'Lawyer not found.'}, status=status.HTTP_404_NOT_FOUND)

    profile = LawyerProfile.objects(user=lawyer).first()
    if not profile:
        return Response({'error': 'Lawyer is not available for connections yet.'}, status=status.HTTP_400_BAD_REQUEST)

    existing_request = LawyerConnectionRequest.objects(
        client=request.user, lawyer=lawyer, status='pending'
    ).first()
    if existing_request:
        serializer = LawyerConnectionRequestSerializer(existing_request)
        return Response({
            'message': 'You already have a pending connection request with this lawyer.',
            'request': serializer.data
        }, status=status.HTTP_200_OK)

    message = request.data.get('message', '').strip()
    preferred_time_str = request.data.get('preferred_time')

    preferred_time = None
    if preferred_time_str:
        try:
            preferred_time = datetime.fromisoformat(preferred_time_str.replace('Z', '+00:00'))
        except ValueError:
            return Response({'error': 'Invalid preferred time format. Use ISO 8601 format.'}, status=status.HTTP_400_BAD_REQUEST)

    print(f"DEBUG: connect_with_lawyer_view - request.data: {request.data}")
    print(f"DEBUG: connect_with_lawyer_view - message: '{message}', preferred_time_str: '{preferred_time_str}', preferred_time: {preferred_time}")
    print(f"DEBUG: connect_with_lawyer_view - Using client email: {request.user.email}")
    
    try:
        connection_request = LawyerConnectionRequest.objects.create(
            client=request.user,
            lawyer=lawyer,
            message=message,
            preferred_time=preferred_time,
        )
    except errors.ValidationError as ve:
        print(f"ERROR: MongoEngine Validation Error during connection request creation: {ve.errors}")
        return Response({'error': f"Validation error: {ve.errors}"}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({'error': f'An unexpected error occurred during connection request creation: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    serializer = LawyerConnectionRequestSerializer(connection_request)
    return Response({
        'message': 'Connection request submitted successfully.',
        'request': serializer.data,
    }, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def lawyer_dashboard_view(request):
    """Return dashboard information for a lawyer"""
    if not request.user.is_lawyer:
        return Response({'error': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)

    profile = LawyerProfile.objects(user=request.user).first()
    profile_data = LawyerProfileSerializer(profile).data if profile else None

    connection_requests = LawyerConnectionRequest.objects(lawyer=request.user).order_by('-created_at')
    connection_serializer = LawyerConnectionRequestSerializer(connection_requests, many=True)

    summary = {
        'total_requests': connection_requests.count(),
        'pending_requests': connection_requests.filter(status='pending').count(),
        'accepted_requests': connection_requests.filter(status='accepted').count(),
        'declined_requests': connection_requests.filter(status='declined').count(),
    }

    return Response({
        'profile': profile_data,
        'user': UserSerializer(request.user).data,
        'connections': connection_serializer.data,
        'summary': summary,
    }, status=status.HTTP_200_OK)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def lawyer_connection_update_view(request, connection_id):
    """Allow lawyer to update connection request status"""
    if not request.user.is_lawyer:
        return Response({'error': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)

    connection_request = LawyerConnectionRequest.objects(id=connection_id, lawyer=request.user).first()
    if not connection_request:
        return Response({'error': 'Connection request not found.'}, status=status.HTTP_404_NOT_FOUND)

    serializer = LawyerConnectionStatusSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    new_status = serializer.validated_data['status']
    connection_request.status = new_status
    connection_request.message = serializer.validated_data.get('message', connection_request.message)
    if new_status == 'accepted':
        if not connection_request.meet_link:
            link = connection_request.meeting_link or _generate_meet_link()
            connection_request.meet_link = link
            connection_request.meeting_link = link
    connection_request.save()

    # Create chat conversation when lawyer accepts
    if new_status == 'accepted':
        existing_chat = ChatConversation.objects(
            connection_request=connection_request
        ).first()
        if not existing_chat:
            try:
                chat_conversation = ChatConversation.objects.create(
                    connection_request=connection_request,
                    client=connection_request.client,
                    lawyer=connection_request.lawyer,
                    is_active=True,
                )
                print(f"Created chat conversation {chat_conversation.id} for connection {connection_request.id}")
                
                # Send welcome message
                welcome_msg = f"Connection accepted! You can now chat with {connection_request.client.name or connection_request.client.username}."
                ChatMessage.objects.create(
                    conversation=chat_conversation,
                    sender=request.user,
                    message=welcome_msg,
                    message_type='system',
                )
                print(f"Created welcome message for conversation {chat_conversation.id}")

                # Send Google Meet link message
                if connection_request.meet_link:
                    ChatMessage.objects.create(
                        conversation=chat_conversation,
                        sender=request.user,
                        message=connection_request.meet_link,
                        message_type='meet_link',
                    )
                    print(f"Created meet_link message for conversation {chat_conversation.id}")
            except Exception as e:
                print(f"Error creating chat conversation: {e}")
                import traceback
                traceback.print_exc()

    response_serializer = LawyerConnectionRequestSerializer(connection_request)
    return Response({
        'message': f'Connection request {new_status}.',
        'request': response_serializer.data,
    }, status=status.HTTP_200_OK)

@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def withdraw_connection_view(request, connection_id):
    """Allow a client to withdraw a pending connection request."""
    connection_request = LawyerConnectionRequest.objects(id=connection_id, client=request.user).first()
    if not connection_request:
        return Response({'error': 'Connection request not found.'}, status=status.HTTP_404_NOT_FOUND)

    if connection_request.status != 'pending':
        return Response({'error': 'Only pending requests can be withdrawn.'}, status=status.HTTP_400_BAD_REQUEST)

    connection_request.status = 'withdrawn'
    connection_request.save()

    serializer = LawyerConnectionRequestSerializer(connection_request)
    return Response({
        'message': 'Connection request withdrawn successfully.',
        'request': serializer.data,
    }, status=status.HTTP_200_OK)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def connection_requests_list_view(request):
    """List all connection requests for the authenticated user."""
    user = request.user
    connection_requests = LawyerConnectionRequest.objects(client=user).order_by('-created_at')
    serializer = LawyerConnectionRequestSerializer(connection_requests, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_rating_view(request):
    """Allow a client to rate a lawyer after an accepted connection."""
    serializer = RatingCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    connection_request = LawyerConnectionRequest.objects(
        id=serializer.validated_data['connection_request_id']
    ).first()
    if not connection_request:
        return Response({'error': 'Connection request not found.'}, status=status.HTTP_404_NOT_FOUND)

    if str(connection_request.client.id) != str(request.user.id):
        return Response({'error': 'Only the client on this connection can submit a rating.'}, status=status.HTTP_403_FORBIDDEN)

    if connection_request.status != 'accepted':
        return Response({'error': 'You can only rate an accepted connection.'}, status=status.HTTP_400_BAD_REQUEST)

    if Rating.objects(connection_request=connection_request).first():
        return Response({'error': 'You have already rated this connection.'}, status=status.HTTP_400_BAD_REQUEST)

    rating = Rating.objects.create(
        connection_request=connection_request,
        client=request.user,
        lawyer=connection_request.lawyer,
        score=serializer.validated_data['score'],
        comment=serializer.validated_data.get('comment', ''),
    )
    return Response(RatingSerializer(rating).data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([AllowAny])
def lawyer_ratings_view(request, lawyer_id):
    """List a lawyer's ratings and average score."""
    try:
        lawyer = User.objects(id=lawyer_id, role='lawyer').first()
    except DoesNotExist:
        lawyer = None
    if not lawyer:
        return Response({'error': 'Lawyer not found.'}, status=status.HTTP_404_NOT_FOUND)

    ratings = Rating.objects(lawyer=lawyer).order_by('-created_at')
    scores = [r.score for r in ratings]
    average_score = round(sum(scores) / len(scores), 1) if scores else 0

    return Response({
        'ratings': RatingSerializer(ratings, many=True).data,
        'average_score': average_score,
        'total_ratings': len(scores),
    }, status=status.HTTP_200_OK)