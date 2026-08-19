from rest_framework.pagination import PageNumberPagination


class StandardPageNumberPagination(PageNumberPagination):
    """Permite al cliente elegir el tamaño de página (?page_size=), capado
    para que nadie pida el listado completo de una sola vez."""

    page_size_query_param = "page_size"
    max_page_size = 100
