from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient


class LoginAPIViewTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		self.url = '/auth/login/'
		self.user = get_user_model().objects.create_user(
			username='driver',
			email='driver@example.com',
			password='correct-password',
		)

	def test_login_returns_user_details_and_creates_session(self):
		response = self.client.post(self.url, {
			'email': 'DRIVER@example.com',
			'password': 'correct-password',
		}, format='json')

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data['user'], {
			'id': self.user.pk,
			'email': 'driver@example.com',
		})
		self.assertTrue(response.wsgi_request.user.is_authenticated)

	def test_login_requires_email_and_password(self):
		response = self.client.post(self.url, {'email': ''}, format='json')

		self.assertEqual(response.status_code, 400)
		self.assertIn('email', response.data)
		self.assertIn('password', response.data)

	def test_login_rejects_invalid_credentials(self):
		response = self.client.post(self.url, {
			'email': 'driver@example.com',
			'password': 'wrong-password',
		}, format='json')

		self.assertEqual(response.status_code, 401)
		self.assertEqual(response.data['detail'], 'Invalid email or password.')

	def test_login_rejects_inactive_account(self):
		self.user.is_active = False
		self.user.save(update_fields=['is_active'])

		response = self.client.post(self.url, {
			'email': 'driver@example.com',
			'password': 'correct-password',
		}, format='json')

		self.assertEqual(response.status_code, 401)
		self.assertEqual(response.data['detail'], 'This account is inactive.')
