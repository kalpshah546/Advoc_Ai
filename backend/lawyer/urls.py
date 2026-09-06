from django.urls import path
from .views import (
    lawyer_list_view,
    lawyer_detail_view,
    connect_with_lawyer_view,
    lawyer_dashboard_view,
    lawyer_connection_update_view,
    withdraw_connection_view,
    connection_requests_list_view,
    create_rating_view,
    lawyer_ratings_view,
)

urlpatterns = [
    path('', lawyer_list_view, name='lawyer_list'),
    path('dashboard/', lawyer_dashboard_view, name='lawyer_dashboard'),
    path('connections/', connection_requests_list_view, name='connection_requests_list'),
    path('ratings/', create_rating_view, name='create_rating'),
    path('<str:lawyer_id>/ratings/', lawyer_ratings_view, name='lawyer_ratings'),
    path('<str:lawyer_id>/', lawyer_detail_view, name='lawyer_detail'),
    path('<str:lawyer_id>/connect/', connect_with_lawyer_view, name='connect_lawyer'),
    path('connections/<str:connection_id>/', lawyer_connection_update_view, name='lawyer_connection_update'),
    path('connections/<str:connection_id>/withdraw/', withdraw_connection_view, name='withdraw_connection'),
]
