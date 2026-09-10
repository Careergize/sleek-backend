from django.contrib.auth import authenticate, get_user_model, login
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import LoginSerializer


class LoginAPIView(APIView):
	"""Authenticate a user with an email address and password."""

	def post(self, request):
		serializer = LoginSerializer(data=request.data)
		serializer.is_valid(raise_exception=False)

		if serializer.errors:
			return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

		email = serializer.validated_data['email']
		password = serializer.validated_data['password']
		user_model = get_user_model()
		user = user_model.objects.filter(email__iexact=email).first()

		if user is None:
			return Response(
				{'detail': 'Invalid email or password.'},
				status=status.HTTP_401_UNAUTHORIZED,
			)

		if not user.is_active:
			return Response(
				{'detail': 'This account is inactive.'},
				status=status.HTTP_401_UNAUTHORIZED,
			)

		authenticated_user = authenticate(
			request,
			password=password,
			**{user_model.USERNAME_FIELD: user.get_username()},
		)
		if authenticated_user is None:
			return Response(
				{'detail': 'Invalid email or password.'},
				status=status.HTTP_401_UNAUTHORIZED,
			)

		login(request, authenticated_user)
		return Response({
			'message': 'Login successful.',
			'user': {
				'id': authenticated_user.pk,
				'email': authenticated_user.email,
			},
		}, status=status.HTTP_200_OK)
