import logging
import uuid

from django.conf import settings


logger = logging.getLogger('config.request_errors')


class RequestTraceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = uuid.uuid4().hex[:12]
        response = self.get_response(request)
        response['X-Request-ID'] = request.request_id
        return response

    def process_exception(self, request, exception):
        user = getattr(request, 'user', None)
        user_id = user.pk if user is not None and user.is_authenticated else None
        view_name = getattr(getattr(request, 'resolver_match', None), 'view_name', None)
        logger.exception(
            'Unhandled request error request_id=%s user_id=%s method=%s view=%s',
            request.request_id,
            user_id,
            request.method,
            view_name,
            extra={'request_id': request.request_id},
        )
        if settings.DEBUG:
            return None
