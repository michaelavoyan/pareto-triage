from django.urls import include, path

urlpatterns = [
    path('home/', views.home),
    include('shop.urls'),
]
