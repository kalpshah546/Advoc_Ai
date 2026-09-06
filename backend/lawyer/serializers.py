from rest_framework import serializers
from authentication.serializers import UserSerializer
from .models import LawyerProfile, LawyerConnectionRequest, Rating

class LawyerProfileSerializer(serializers.Serializer):
    """Serializer for lawyer public profile"""

    id = serializers.CharField(read_only=True)
    user = UserSerializer(read_only=True)
    phone = serializers.CharField(read_only=True)
    education = serializers.CharField(read_only=True)
    experience_years = serializers.IntegerField(read_only=True)
    law_firm = serializers.CharField(read_only=True)
    specializations = serializers.ListField(child=serializers.CharField(), read_only=True)
    license_number = serializers.CharField(read_only=True)
    bar_council_id = serializers.CharField(read_only=True)
    consultation_fee = serializers.CharField(read_only=True)
    bio = serializers.CharField(read_only=True)
    verification_status = serializers.CharField(read_only=True)
    verification_notes = serializers.CharField(read_only=True)


class LawyerConnectionRequestSerializer(serializers.Serializer):
    """Serializer for lawyer connection requests"""

    id = serializers.CharField(read_only=True)
    client = UserSerializer(read_only=True)
    lawyer = UserSerializer(read_only=True)
    message = serializers.CharField(required=False, allow_blank=True)
    status = serializers.CharField(read_only=True)
    preferred_time = serializers.DateTimeField(required=False, allow_null=True)
    meet_link = serializers.CharField(read_only=True)
    meeting_link = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class LawyerConnectionStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=['accepted', 'declined'])
    message = serializers.CharField(required=False, allow_blank=True)


class RatingSerializer(serializers.Serializer):
    id = serializers.CharField(read_only=True)
    connection_request = serializers.SerializerMethodField()
    client = UserSerializer(read_only=True)
    lawyer = UserSerializer(read_only=True)
    score = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(required=False, allow_blank=True, default='')
    created_at = serializers.DateTimeField(read_only=True)

    def get_connection_request(self, obj):
        return str(obj.connection_request.id) if obj.connection_request else None


class RatingCreateSerializer(serializers.Serializer):
    connection_request_id = serializers.CharField()
    score = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(required=False, allow_blank=True, default='')
