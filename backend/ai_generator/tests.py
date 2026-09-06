from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from unittest.mock import patch
import google.api_core.exceptions
from authentication.models import User
from ai_generator.utils import get_gemini_response, GeminiQuotaExhaustedError


import mongomock
from mongoengine import connect, disconnect


class AIGeneratorQuotaTest(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        try:
            disconnect(alias='default')
        except Exception:
            pass
        cls.db_name = 'test_ai_generator_db'
        connect(cls.db_name, host='mongodb://localhost', mongo_client_class=mongomock.MongoClient, alias='default')

    @classmethod
    def tearDownClass(cls):
        disconnect(alias='default')
        super().tearDownClass()

    def setUp(self):
        User.objects.all().delete()
        self.client = APIClient()
        self.user = User.create_user(
            email='testai@example.com',
            username='aiuser',
            password='password123'
        )
        self.client.force_authenticate(user=self.user)

    @patch('ai_generator.utils.get_gemini_client')
    def test_get_gemini_response_raises_quota_exception(self, mock_get_client):
        # Setup mock to raise ResourceExhausted exception
        mock_model = mock_get_client.return_value.GenerativeModel.return_value
        mock_model.generate_content.side_effect = google.api_core.exceptions.ResourceExhausted("Quota exceeded")

        with self.assertRaises(GeminiQuotaExhaustedError):
            get_gemini_response("Test prompt")

    @patch('ai_generator.views.get_gemini_response')
    def test_chat_view_returns_500_on_quota_exhausted(self, mock_get_gemini_response):
        mock_get_gemini_response.side_effect = GeminiQuotaExhaustedError("Quota exceeded for Gemini API. Please try again later.")

        response = self.client.post(
            '/api/generate/chat/',
            {'messages': [{'text': 'Hello AI'}]},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn('error', response.data)
        self.assertIn('Quota exceeded', response.data['error'])
