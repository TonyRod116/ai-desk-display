"""Never forward authenticated requests or clock images through redirects."""
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def open_direct(request, timeout=20, no_proxy=False):
    handlers = [NoRedirect()]
    if no_proxy:
        handlers.append(ProxyHandler({}))
    return build_opener(*handlers).open(request, timeout=timeout)
