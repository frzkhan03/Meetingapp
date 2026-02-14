from django.contrib import admin
from django.db.models import Count
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from .models import Profile, Organization, OrganizationMembership


class OrganizationMembershipInline(TabularInline):
    model = OrganizationMembership
    extra = 0
    fields = ['user', 'role', 'is_active', 'joined_at']
    readonly_fields = ['joined_at']
    autocomplete_fields = ['user']


@admin.register(Organization)
class OrganizationAdmin(ModelAdmin):
    list_display = [
        'name', 'slug', 'subdomain', 'is_active',
        'member_count', 'has_branding', 'recording_to_s3', 'created_at',
    ]
    list_filter = ['is_active', 'recording_to_s3', 'created_at']
    search_fields = ['name', 'slug', 'subdomain', 'domain']
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ['id', 'created_at', 'updated_at', 'color_preview']
    list_per_page = 25
    inlines = [OrganizationMembershipInline]

    fieldsets = (
        ('Organization Info', {
            'fields': ('id', 'name', 'slug', 'domain', 'is_active'),
        }),
        ('Branding', {
            'fields': ('logo', 'primary_color', 'secondary_color', 'color_preview', 'subdomain'),
            'classes': ('collapse',),
        }),
        ('Features', {
            'fields': ('recording_to_s3',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _member_count=Count('memberships', distinct=True)
        )

    @admin.display(description='Members', ordering='_member_count')
    def member_count(self, obj):
        return obj._member_count

    @admin.display(description='Branding', boolean=True)
    def has_branding(self, obj):
        return bool(obj.primary_color or obj.logo)

    @admin.display(description='Colors')
    def color_preview(self, obj):
        html = ''
        if obj.primary_color:
            html += (
                f'<span style="display:inline-block;width:24px;height:24px;'
                f'background:{obj.primary_color};border-radius:4px;'
                f'border:1px solid #ccc;vertical-align:middle;margin-right:8px;">'
                f'</span> Primary: {obj.primary_color}'
            )
        if obj.secondary_color:
            html += (
                f'<br><span style="display:inline-block;width:24px;height:24px;'
                f'background:{obj.secondary_color};border-radius:4px;'
                f'border:1px solid #ccc;vertical-align:middle;margin-right:8px;">'
                f'</span> Secondary: {obj.secondary_color}'
            )
        return format_html(html) if html else '-'


@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(ModelAdmin):
    list_display = ['user', 'organization', 'role_badge', 'is_active', 'joined_at']
    list_filter = ['role', 'is_active', 'organization']
    search_fields = ['user__username', 'user__email', 'organization__name']
    autocomplete_fields = ['user', 'organization']
    list_per_page = 50

    @admin.display(description='Role')
    def role_badge(self, obj):
        colors = {
            'owner': '#7c3aed',
            'admin': '#2563eb',
            'member': '#6b7280',
        }
        color = colors.get(obj.role, '#6b7280')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:9999px;font-size:0.75rem;">{}</span>',
            color, obj.get_role_display()
        )


@admin.register(Profile)
class ProfileAdmin(ModelAdmin):
    list_display = ['user', 'user_email', 'current_organization', 'has_avatar', 'created_at']
    list_filter = ['current_organization', 'created_at']
    search_fields = ['user__username', 'user__email']
    autocomplete_fields = ['user', 'current_organization']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        (None, {
            'fields': ('user', 'current_organization', 'avatar'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description='Email')
    def user_email(self, obj):
        return obj.user.email

    @admin.display(description='Avatar', boolean=True)
    def has_avatar(self, obj):
        return bool(obj.avatar)
