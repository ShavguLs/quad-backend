from django.conf import settings


class ContentSecurityPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if self._should_add_csp(request, response):
            response['Content-Security-Policy'] = settings.CONTENT_SECURITY_POLICY

        return response

    @staticmethod
    def _should_add_csp(request, response):
        if response.has_header('Content-Security-Policy'):
            return False

        if request.path.startswith('/admin/'):
            return False

        return True
