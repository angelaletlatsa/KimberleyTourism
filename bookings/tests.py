from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from accounts.models import Profile
from bookings.models import Booking
from guides.models import GuideProfile
from tourist.models import TouristProfile


class BookingApprovalStateTests(TestCase):
    def test_booking_approval_properties(self):
        pending_unapproved = Booking(status='pending', admin_approved=False)
        self.assertTrue(pending_unapproved.is_awaiting_admin)
        self.assertFalse(pending_unapproved.is_awaiting_guide)
        self.assertTrue(pending_unapproved.can_admin_approve)

        pending_approved = Booking(status='pending', admin_approved=True)
        self.assertFalse(pending_approved.is_awaiting_admin)
        self.assertTrue(pending_approved.is_awaiting_guide)
        self.assertFalse(pending_approved.can_admin_approve)

        confirmed = Booking(status='confirmed', admin_approved=True)
        self.assertFalse(confirmed.is_awaiting_admin)
        self.assertFalse(confirmed.is_awaiting_guide)
        self.assertFalse(confirmed.can_admin_approve)


class BookingParticipantConstraintTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username='db-constraint-tourist')
        profile = Profile.objects.create(user=user, role='tourist')
        self.tourist = TouristProfile.objects.create(profile=profile)

    def test_database_rejects_participant_counts_outside_supported_range(self):
        for participant_count in (0, 201):
            with self.subTest(participant_count=participant_count):
                with transaction.atomic():
                    with self.assertRaises(IntegrityError):
                        Booking.objects.create(
                            visitor=self.tourist,
                            booking_date=date(2030, 1, 1),
                            booking_time=time(10, 0),
                            number_of_participants=participant_count,
                        )


class BookingTransitionGuardTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        visitor_user = user_model.objects.create_user(username='transition-tourist')
        visitor_profile = Profile.objects.create(user=visitor_user, role='tourist')
        self.visitor = TouristProfile.objects.create(profile=visitor_profile)

        guide_user = user_model.objects.create_user(username='transition-guide')
        guide_profile = Profile.objects.create(user=guide_user, role='guide')
        schedule = {
            day: {'available': True, 'start': '09:00', 'end': '17:00'}
            for day in ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
        }
        self.guide = GuideProfile.objects.create(
            profile=guide_profile,
            verification_status='approved',
            availability_schedule=schedule,
        )
        self.booking_date = timezone.localdate() + timedelta(days=14)

    def _pending_booking(self):
        return Booking.objects.create(
            visitor=self.visitor,
            guide=self.guide,
            booking_date=self.booking_date,
            booking_time=time(10, 0),
            admin_approved=True,
        )

    def test_guide_cannot_confirm_overlapping_bookings(self):
        first = self._pending_booking()
        second = self._pending_booking()

        first.accept(guide=self.guide)

        with self.assertRaises(ValidationError):
            second.accept(guide=self.guide)

        second.refresh_from_db()
        self.assertEqual(second.status, 'pending')

    def test_future_booking_cannot_be_marked_complete(self):
        booking = self._pending_booking()
        booking.status = 'confirmed'
        booking.save(update_fields=['status'])

        with self.assertRaises(ValidationError):
            booking.complete()

        booking.refresh_from_db()
        self.assertEqual(booking.status, 'confirmed')
