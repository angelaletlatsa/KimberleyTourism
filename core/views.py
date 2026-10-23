from django.http import JsonResponse
from django.shortcuts import render


def home_view(request):
    return render(request, 'accounts/home.html')


def about_view(request):
    return render(request, 'core/about.html', {'active_page': 'about'})


def how_it_works_view(request):
    return render(request, 'core/how_it_works.html', {'active_page': 'how_it_works'})


def contact_view(request):
    return render(request, 'core/contact.html', {'active_page': 'contact'})


def server_error(request):
    request_id = getattr(request, 'request_id', 'unavailable')
    message = (
        'Something went wrong. Please wait 5 seconds, then try again. '
        'If the problem continues, contact support and share the reference ID.'
    )

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': False,
            'error': message,
            'reference_id': request_id,
        }, status=500)

    return render(
        request,
        'core/500.html',
        {'request_id': request_id},
        status=500,
    )