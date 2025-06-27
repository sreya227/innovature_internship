from django.contrib import admin
from django.urls import path
from . import views
from django.contrib.auth.views import LogoutView
from django.contrib.auth.decorators import login_required

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.home_view, name='home'),
    path('signup/', views.signup_view, name='signup'),
    path('verify-otp/', views.verify_otp_view, name='verify_otp'),
    path('login/', views.login_view, name='login'),
    path('groups/', views.groups_view, name='groups'),
    path('groups/create/', views.create_group_view, name='create_group'),
    path('groups/<int:group_id>/', views.group_detail_view, name='group_detail'),
    path('groups/<int:group_id>/create-split/', views.create_split_view, name='create_split'),
    path('splits/<int:split_id>/', views.split_detail_view, name='split_detail'),
    path('splits/<int:split_id>/record-settlement/', views.record_settlement_view, name='record_settlement'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('transactions/', views.transactions_view, name='transactions'),
    path('logout/', login_required(LogoutView.as_view(next_page='login')),name='logout'),
    path('groups/<int:group_id>/leave/', views.leave_group_view, name='leave_group'),
    path('groups/<int:group_id>/info/', views.group_info_view, name='group_info'),
    path('groups/<int:group_id>/info/', views.group_info_view, name='group_info'),
    path('groups/<int:group_id>/add/', views.add_member_view, name='add_member'),
    path('groups/<int:group_id>/remove/', views.remove_member_view, name='remove_member'),
    path('dues/', views.dues_view, name='dashboard_dues'),
path('groups/<int:group_id>/dues/', views.dues_view, name='group_dues'),
path('groups/<int:group_id>/delete/', views.delete_group_view, name='delete_group'),
path('forgot-password/', views.forgot_password_request_view, name='forgot_password'),
path('verify-reset-otp/', views.verify_reset_otp_view, name='verify_reset_otp'),
path('reset-password/', views.reset_password_view, name='reset_password'),
]


