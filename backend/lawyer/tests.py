from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from mongoengine import connect, disconnect
import mongomock

from authentication.models import User
from lawyer.models import LawyerProfile, LawyerConnectionRequest
from chat.models import ChatConversation, ChatMessage


class LawyerConnectionAcceptTest(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        disconnect_all_connections()
        cls.db_name = 'test_lawyer_connection_db'
        connect(cls.db_name, host='mongodb://localhost', mongo_client_class=mongomock.MongoClient, alias='default')

    @classmethod
    def tearDownClass(cls):
        from mongoengine import disconnect
        disconnect(alias='default')
        super().tearDownClass()

    def setUp(self):
        User.objects.all().delete()
        LawyerProfile.objects.all().delete()
        LawyerConnectionRequest.objects.all().delete()
        ChatConversation.objects.all().delete()
        ChatMessage.objects.all().delete()

        self.client_user = User.create_user(
            email='client@example.com',
            username='clientuser',
            password='password123',
            role='client'
        )

        self.lawyer_user = User.create_user(
            email='lawyer@example.com',
            username='lawyeruser',
            password='password123',
            role='lawyer'
        )

        self.lawyer_profile = LawyerProfile.objects.create(
            user=self.lawyer_user,
            license_number='LIC123456',
            bar_council_id='BAR123456',
            verification_status='approved'
        )

        self.connection_request = LawyerConnectionRequest.objects.create(
            client=self.client_user,
            lawyer=self.lawyer_user,
            message='Initial consultation request',
            status='pending'
        )

        self.api_client = APIClient()

    def test_accept_connection_request_populates_meet_link_and_creates_chat_message(self):
        self.api_client.force_authenticate(user=self.lawyer_user)

        url = f'/api/lawyer/connections/{self.connection_request.id}/'
        response = self.api_client.patch(url, {'status': 'accepted'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify meet_link in response data
        request_data = response.data.get('request', {})
        self.assertIn('meet_link', request_data)
        self.assertTrue(request_data['meet_link'].startswith('https://meet.google.com/'))

        # Verify meet_link in updated database document
        self.connection_request.reload()
        self.assertTrue(self.connection_request.meet_link.startswith('https://meet.google.com/'))

        # Verify ChatConversation creation
        conversation = ChatConversation.objects(connection_request=self.connection_request).first()
        self.assertIsNotNone(conversation)

        # Verify ChatMessage with meet_link type exists
        meet_message = ChatMessage.objects(
            conversation=conversation,
            message_type='meet_link'
        ).first()
        self.assertIsNotNone(meet_message)
        self.assertEqual(meet_message.message, self.connection_request.meet_link)


def disconnect_all_connections():
    from mongoengine import disconnect
    try:
        disconnect(alias='default')
    except Exception:
        pass
