from django.test import TestCase, override_settings
from django.urls import path


def _raise_server_error(request):
    raise RuntimeError('test-only private exception detail')


urlpatterns = [
    path('broken/', _raise_server_error),
]
handler500 = 'core.views.server_error'


@override_settings(DEBUG=False, ROOT_URLCONF='core.tests')
class RequestErrorTraceTests(TestCase):
    def setUp(self):
        self.client.raise_request_exception = False

    def test_server_error_is_logged_and_returns_safe_reference(self):
        with self.assertLogs('config.request_errors', level='ERROR') as captured:
            response = self.client.get(
                '/broken/',
                HTTP_X_REQUESTED_WITH='XMLHttpRequest',
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response['X-Request-ID'], response.json()['reference_id'])
        self.assertIn('Please wait 5 seconds', response.json()['error'])
        self.assertNotIn('private exception detail', response.content.decode())
        self.assertIn(response['X-Request-ID'], captured.output[0])

    def test_html_server_error_page_shows_reference_id(self):
        response = self.client.get('/broken/')

        self.assertEqual(response.status_code, 500)
        self.assertContains(response, 'Please wait 5 seconds', status_code=500)
        self.assertContains(response, response['X-Request-ID'], status_code=500)


class LandingPageInformationTests(TestCase):
    def test_landing_page_links_open_their_own_pages(self):
        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/about/"')
        self.assertContains(response, 'href="/how-it-works/"')
        self.assertContains(response, 'href="/contact/"')
        self.assertNotContains(response, 'Meet the Guides')
        content = response.content.decode()
        self.assertRegex(content, r'href="/about/"[^>]*>\s*About Kimberley')
        self.assertRegex(content, r'href="/how-it-works/"[^>]*>\s*How It Works')
        self.assertRegex(content, r'href="/contact/"[^>]*>\s*Contact')

    def test_information_pages_render_expected_content_and_navigation(self):
        pages = (
            ('/about/', 'About Kimberley', 'Northern Cape'),
            ('/how-it-works/', 'How It Works', 'Browse experiences'),
            ('/contact/', 'Contact', 'explore.kimberleytours@gmail.com'),
        )

        for url, heading, expected_content in pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, heading)
                self.assertContains(response, expected_content)
                self.assertContains(response, 'href="/about/"')
                self.assertContains(response, 'href="/how-it-works/"')
                self.assertContains(response, 'href="/contact/"')
