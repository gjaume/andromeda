from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from unfold.admin import ModelAdmin

from .models import PopeyeApiCall

admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    list_display = ("email", "first_name", "last_name", "is_active", "is_staff", "last_login")
    list_filter = ("is_active", "is_staff", "groups")
    search_fields = ("email", "first_name", "last_name")


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    pass


@admin.register(PopeyeApiCall)
class PopeyeApiCallAdmin(ModelAdmin):
    list_display = ("created_at", "user", "method", "path", "status_code", "duration_ms")
    list_filter = ("method", "status_code")
    search_fields = ("path", "user__email")
    readonly_fields = [f.name for f in PopeyeApiCall._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
