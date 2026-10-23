from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile
from bookings.models import Booking
from guides.models import GuideProfile
from tourist.models import TouristProfile


class TouristPlanTripTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='tourist_user',
            email='tourist@example.com',
            password='StrongPass123!'
        )
        self.profile = Profile.objects.create(user=self.user, role='tourist')
        TouristProfile.objects.create(profile=self.profile)
        self.client = Client()
        self.client.force_login(self.user)

    def test_plan_my_trip_page_renders(self):
        response = self.client.get(reverse('tourist:plan_my_trip'))
        self.assertEqual(response.status_code, 200)


class DirectGuideBookingTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        tourist_user = user_model.objects.create_user(
            username='booking-tourist',
            password='StrongPass123!',
        )
        tourist_profile = Profile.objects.create(user=tourist_user, role='tourist')
        self.tourist = TouristProfile.objects.create(profile=tourist_profile)

        guide_user = user_model.objects.create_user(
            username='booking-guide',
            email='guide@example.com',
        )
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
        self.client = Client()
        self.client.force_login(tourist_user)
        self.booking_date = timezone.localdate() + timedelta(days=7)
        self.url = reverse('tourist:book_guide_directly', args=[self.guide.id])
        self.post_data = {
            'booking_date': self.booking_date.isoformat(),
            'booking_time': '10:00',
            'participants': '1',
            'destination_name[]': ['Kimberley Museum'],
        }

    def test_guide_profile_displays_guide_email_instead_of_share_profile(self):
        response = self.client.get(
            reverse('tourist:guide_profile', args=[self.guide.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'guide@example.com')
        self.assertContains(response, 'mailto:guide@example.com')
        self.assertNotContains(response, 'Share Profile')

    def test_booking_detail_shows_tourist_layout_and_completion_action_when_eligible(self):
        booking = Booking.objects.create(
            visitor=self.tourist,
            guide=self.guide,
            booking_date=timezone.localdate(),
            booking_time='10:00',
            number_of_participants=1,
            status='confirmed',
        )

        response = self.client.get(
            reverse('bookings:detail', args=[booking.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Booking details')
        self.assertContains(response, 'Back to My Bookings')
        self.assertContains(response, 'Mark tour as complete')
        self.assertContains(response, 'My Itinerary')
        self.assertNotContains(response, 'Administrator')
        self.assertNotContains(response, 'Admin Actions')

    def test_marking_tour_complete_returns_to_my_bookings_and_places_it_in_past(self):
        booking = Booking.objects.create(
            visitor=self.tourist,
            guide=self.guide,
            booking_date=timezone.localdate(),
            booking_time='10:00',
            number_of_participants=1,
            status='confirmed',
        )

        response = self.client.post(
            reverse('bookings:mark_complete', args=[booking.id])
        )

        self.assertRedirects(response, reverse('bookings:my_bookings'))
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'completed')

        bookings_response = self.client.get(reverse('bookings:my_bookings'))
        self.assertContains(bookings_response, 'Past')
        self.assertTrue(
            bookings_response.context['past_bookings'].filter(pk=booking.pk).exists()
        )

    def test_completed_booking_in_past_shows_leave_review_button(self):
        booking = Booking.objects.create(
            visitor=self.tourist,
            guide=self.guide,
            booking_date=timezone.localdate() - timedelta(days=1),
            booking_time='10:00',
            number_of_participants=1,
            status='completed',
        )

        response = self.client.get(reverse('bookings:my_bookings'))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.context['past_bookings'].filter(pk=booking.pk).exists()
        )
        self.assertContains(
            response,
            f'href="{reverse("reviews:create", args=[booking.id])}"',
        )
        self.assertContains(response, 'Leave Review')

    def test_invalid_participant_values_do_not_create_a_booking_or_crash(self):
        for value in ('not-a-number', '0', '201'):
            with self.subTest(value=value):
                response = self.client.post(
                    self.url,
                    {**self.post_data, 'participants': value},
                )
                self.assertEqual(response.status_code, 302)
                self.assertFalse(Booking.objects.exists())

    def test_booking_outside_guide_hours_is_rejected(self):
        response = self.client.post(
            self.url,
            {**self.post_data, 'booking_time': '17:00'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Booking.objects.exists())

    def test_valid_booking_with_maximum_participants_is_created(self):
        response = self.client.post(
            self.url,
            {**self.post_data, 'participants': '200'},
        )
        self.assertEqual(response.status_code, 302)
        booking = Booking.objects.get()
        self.assertEqual(booking.visitor, self.tourist)
        self.assertEqual(booking.guide, self.guide)
        self.assertEqual(booking.number_of_participants, 200)
        self.assertEqual(booking.status, 'pending')
