from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/room/(?P<room_id>[a-z]{3}-[a-z]{4}-[a-z]{3}(?:-(?:br-[a-f0-9]{6}|\d{3}))?)/$', consumers.RoomConsumer.as_asgi()),
    re_path(r'ws/user/$', consumers.UserConsumer.as_asgi()),
]
