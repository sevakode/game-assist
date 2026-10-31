"""RFC 9207 response decoration for the pinned MCP SDK 1.29.0.

The SDK remains responsible for request validation and choosing whether an error
may redirect. This adapter only decorates an error redirect it already returned.
"""
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from starlette.routing import Route


def with_issuer(location, issuer):
    parts = urlsplit(location)
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if key != 'iss']
    query.append(('iss', issuer))
    return urlunsplit(parts._replace(query=urlencode(query)))


def identify_authorization_errors(routes, issuer):
    for index, route in enumerate(routes):
        if isinstance(route, Route) and route.path == '/authorize':
            original = route.endpoint

            async def identified(request):
                response = await original(request)
                location = response.headers.get('location')
                if response.status_code == 302 and location and any(
                    key == 'error' for key, _ in parse_qsl(urlsplit(location).query)
                ):
                    response.headers['location'] = with_issuer(location, issuer)
                return response

            routes[index] = Route(route.path, identified, methods=route.methods,
                                  name=route.name, include_in_schema=route.include_in_schema)
            return
    raise RuntimeError('Expected MCP SDK authorization route')
