"""Declare the missing AMD dependencies in the pinned Document Server build."""

import gzip
import hashlib
from pathlib import Path


DOCUMENT_SERVER = Path('/var/www/onlyoffice/documentserver')
COMPONENTS = DOCUMENT_SERVER / 'web-apps/apps/common/main/lib/component'
EDITOR_API = DOCUMENT_SERVER / 'web-apps/apps/api/documents/api.js'
NGINX_CACHE = Path('/etc/nginx/includes/ds-cache.conf')
ORIGINAL_TAG = b'9dd56f3cd6a34c3086bce4a869f9c9c6'
ORIGINAL_COMPONENTS = {
    'ColorPaletteExt.js': '9d92f386284e2f226e9e24455eb70b7020edac0aec5c175a8d4e92633dc0145c',
    'HSBColorPicker.js': '9025828cef1c1603073203d981e7b1a3883d990af11122d13d67b8d0d37dff2f',
    'MaskedField.js': 'd1b8f3efa10efc1d82b5f89f134628eda89e80957addfbbfeca7e74ba370a9ed',
}


def read_pinned(path, digest):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f'Unexpected source in pinned Document Server image: {path}')
    return data


def replace_once(data, old, new, path):
    if data.count(old) != 1:
        raise ValueError(f'Expected exactly one patch location: {path}')
    return data.replace(old, new, 1)


def main():
    scripts = {}
    for name, digest in ORIGINAL_COMPONENTS.items():
        path = COMPONENTS / name
        scripts[path] = replace_once(
            read_pinned(path, digest),
            b'define([], function',
            b"define(['common/main/lib/component/BaseView'], function",
            path,
        )

    # Both the embed API and nginx mint asset URLs. Keep them in the same
    # namespace so clients with immutable cached assets fetch the patched JS.
    cache_tag = hashlib.sha256(ORIGINAL_TAG + b''.join(scripts.values())).hexdigest()[:32]
    scripts[EDITOR_API] = replace_once(
        read_pinned(EDITOR_API, 'f877f2acde3f6c25d65788b671c413fcdb65a6bd425cb54f8833ec2266271ea6'),
        ORIGINAL_TAG,
        cache_tag.encode('ascii'),
        EDITOR_API,
    )
    cache_config = replace_once(
        read_pinned(NGINX_CACHE, '574a1a54b06c86fa2bfd717bd028587ca6d7d381929d5402208f5241e947fcca'),
        ORIGINAL_TAG,
        cache_tag.encode('ascii'),
        NGINX_CACHE,
    )

    for path, content in scripts.items():
        compressed = path.with_suffix('.js.gz')
        if gzip.decompress(compressed.read_bytes()) != path.read_bytes():
            raise ValueError(f'Precompressed script differs from source: {compressed}')
        path.write_bytes(content)
        compressed.write_bytes(gzip.compress(content, compresslevel=9, mtime=0))
    NGINX_CACHE.write_bytes(cache_config)
    print(f'Document Server assets use cache tag {cache_tag}')


if __name__ == '__main__':
    main()
