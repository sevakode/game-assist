"""Start the local single-user companion. Never binds publicly."""
import os
import sys
import uvicorn


def main():
    if len(os.getenv('SGC_TOKEN', '')) < 32:
        sys.exit('Set SGC_TOKEN to a random secret of at least 32 characters. Do not share it in chat.')
    uvicorn.run('server.app:app', host='127.0.0.1', port=8000, access_log=False)


if __name__ == '__main__':
    main()
