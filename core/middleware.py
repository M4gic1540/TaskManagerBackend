"""Security headers no cubiertos por SecurityMiddleware default."""

_DOCS_PATH_PREFIXES = ("/api/docs/", "/api/redoc/")

# CSP relajado, solo para las páginas de documentación interactiva:
# Swagger UI / ReDoc cargan JS/CSS/fuentes desde jsdelivr y usan
# estilos/scripts inline para renderizar. El resto de la API (todo
# JSON) mantiene el CSP estricto de siempre.
_DOCS_CSP = (
    "default-src 'self'; "
    "img-src 'self' data: https://cdn.jsdelivr.net https://fastapi.tiangolo.com; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "font-src 'self' https://fonts.gstatic.com; "
    "connect-src 'self'; "
    "frame-ancestors 'none'"
)

_DEFAULT_CSP = (
    "default-src 'self'; frame-ancestors 'none'; "
    "img-src 'self' data:; script-src 'self'"
)


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        is_docs_page = request.path.startswith(_DOCS_PATH_PREFIXES)
        response["Content-Security-Policy"] = _DOCS_CSP if is_docs_page else _DEFAULT_CSP

        response["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response["X-Content-Type-Options"] = "nosniff"
        return response
