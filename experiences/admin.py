from django.contrib import admin
from .models import Category, Experience, Availability


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'description', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['name', 'description']


@admin.register(Experience)
class ExperienceAdmin(admin.ModelAdmin):
    list_display = ['name', 'provider', 'category',  'price_range', 'status', 'is_available', 'average_rating']
    list_filter = ['status', 'category', 'is_available', 'created_at']
    search_fields = ['name', 'description', 'location']
    readonly_fields = ['average_rating', 'total_reviews', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'short_description', 'provider', 'guide', 'category')
        }),
        ('Location', {
            'fields': ('location', 'address', 'latitude', 'longitude')
        }),
        ('Pricing & Capacity', {
            'fields': ('price', 'capacity', 'min_participants', 'max_participants')
        }),
        ('Duration', {
            'fields': ('duration_minutes', 'duration_hours')
        }),
        ('Availability', {
            'fields': ('is_available', 'available_days', 'available_from', 'available_to')
        }),
        ('Age & Accessibility', {
            'fields': ('min_age', 'max_age', 'is_accessible', 'accessibility_info')
        }),
        ('Images', {
            'fields': ('main_image', 'images')
        }),
        ('Status & Workflow', {
            'fields': ('status', 'submitted_at', 'approved_at', 'approved_by', 'rejection_reason')
        }),
        ('Booking Rules', {
            'fields': ('cancellation_policy', 'booking_notes')
        }),
        ('Ratings', {
            'fields': ('average_rating', 'total_reviews')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )


@admin.register(Availability)
class AvailabilityAdmin(admin.ModelAdmin):
    list_display = ['experience', 'date', 'start_time', 'end_time', 'max_capacity', 'booked_count', 'is_available']
    list_filter = ['is_available', 'date']
    search_fields = ['experience__name']
    ordering = ['-date', 'start_time']