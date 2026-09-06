from mongoengine import (
    Document,
    StringField,
    BooleanField,
    DateTimeField,
    ReferenceField,
    CASCADE,
)
from datetime import datetime
from authentication.models import User
from lawyer.models import LawyerConnectionRequest

class ChatConversation(Document):
    """Chat conversation between lawyer and client"""
    
    connection_request = ReferenceField(LawyerConnectionRequest, required=True, reverse_delete_rule=CASCADE)
    client = ReferenceField(User, required=True, reverse_delete_rule=CASCADE)
    lawyer = ReferenceField(User, required=True, reverse_delete_rule=CASCADE)
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)
    is_active = BooleanField(default=True)
    
    meta = {
        'collection': 'chat_conversations',
        'indexes': [
            {'fields': ['client', 'lawyer']},
            'connection_request',
            'is_active',
        ],
    }
    
    def save(self, *args, **kwargs):
        self.updated_at = datetime.utcnow()
        return super().save(*args, **kwargs)


class ChatMessage(Document):
    """Individual chat messages"""
    
    conversation = ReferenceField('ChatConversation', required=True, reverse_delete_rule=CASCADE)
    sender = ReferenceField(User, required=True, reverse_delete_rule=CASCADE)
    message = StringField(required=True)
    message_type = StringField(
        max_length=32,
        default='text',
        choices=('text', 'document', 'system', 'meet_link'),
    )
    document_id = StringField(max_length=255, default='')  # Reference to document if shared
    document_title = StringField(max_length=255, default='')
    is_read = BooleanField(default=False)
    created_at = DateTimeField(default=datetime.utcnow)
    
    meta = {
        'collection': 'chat_messages',
        'indexes': [
            'conversation',
            'sender',
            'created_at',
            'is_read',
        ],
    }