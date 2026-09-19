"""
URL configuration for sleekbackend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from django.conf import settings
from django.views.static import serve


def api_root(request):
    return JsonResponse({
        'status': 'ok',
        'message': 'Sleek Backend API is running',
        'endpoints': {
            'cars': '/api/cars/',
            'bookings': '/api/bookings/',
            'admin': '/admin/',
        },
    })


urlpatterns = [
    path('', api_root, name='api-root'),
    path('admin/', admin.site.urls),
    path('api/', include('rentals.urls')),
    path('', include('authentication.urls')),  # Include authentication app URLs
]

urlpatterns += [
    path(
        'media/<path:path>',
        serve,
        {'document_root': settings.MEDIA_ROOT},
    ),
]
