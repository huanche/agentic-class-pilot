"""Declare the missing AMD dependencies in the pinned Document Server build."""

import gzip
import hashlib
from pathlib import Path


DOCUMENT_SERVER = Path('/var/www/onlyoffice/documentserver')
COMPONENTS = DOCUMENT_SERVER / 'web-apps/apps/common/main/lib/component'
FLUSH_CACHE = Path('/usr/bin/documentserver-flush-cache')
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

    # ONLYOFFICE generates api.js and the nginx cache tag at startup and after
    # font updates. Include the patched asset data in that shared tag.
    cache_seed = hashlib.sha256(b''.join(scripts.values())).hexdigest().encode('ascii')
    flush_script = replace_once(
        read_pinned(FLUSH_CACHE, '287358871abd69c288e36fe9944aa60977f5b0dd74d1e54d612a1c5550d48d52'),
        b"date +'%Y.%m.%d-%H%M' | openssl md5",
        b"printf '%s\\n' '" + cache_seed + b"' \"$(date +'%Y.%m.%d-%H%M')\" | openssl md5",
        FLUSH_CACHE,
    )

    for path, content in scripts.items():
        compressed = path.with_suffix('.js.gz')
        if gzip.decompress(compressed.read_bytes()) != path.read_bytes():
            raise ValueError(f'Precompressed script differs from source: {compressed}')
        path.write_bytes(content)
        compressed.write_bytes(gzip.compress(content, compresslevel=9, mtime=0))
    FLUSH_CACHE.write_bytes(flush_script)
    print(f'Document Server assets use cache seed {cache_seed.decode("ascii")}')


if __name__ == '__main__':
    main()
