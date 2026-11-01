"""Explicit single-instance deployment entrypoint; no credentials are provisioned."""
import ipaddress
import os

import uvicorn
from .app import Config, create_app


def server_options(environ=None):
    env = os.environ if environ is None else environ
    mode = env.get('GA_DEPLOYMENT_MODE', 'local')
    if mode not in ('local', 'render'):
        raise ValueError('Unknown deployment mode')
    if mode == 'render' and not env.get('DATABASE_URL'):
        raise ValueError('Render requires a persistent DATABASE_URL; ephemeral SQLite is prohibited')
    port = int(env.get('PORT', '8788'))
    if not 1 <= port <= 65535:
        raise ValueError('Invalid PORT')
    trusted = [part.strip() for part in env.get('GA_TRUSTED_PROXY_IPS', '').split(',') if part.strip()]
    for address in trusted:
        try:
            network = ipaddress.ip_network(address, strict=False)
        except ValueError:
            raise ValueError('Trusted proxies must be explicit IP addresses or restricted CIDRs') from None
        if network.prefixlen == 0:
            raise ValueError('Wildcard proxy trust is prohibited')
    return dict(host='0.0.0.0' if mode == 'render' else '127.0.0.1', port=port, workers=1,
                proxy_headers=bool(trusted), forwarded_allow_ips=trusted, access_log=False)


def main():
    options = server_options()
    # create_app installs the allowlist sink. Uvicorn must not replace it.
    uvicorn.run(create_app(Config.from_env()), log_config=None, **options)


if __name__ == '__main__':
    main()
