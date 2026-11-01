"""Construct a reversible lab-only Caddy delta; never replace unrelated routes."""
from pathlib import Path
import argparse
import ipaddress
import os

BEGIN = '# BEGIN AGENTIC ONLYOFFICE LAB'
END = '# END AGENTIC ONLYOFFICE LAB'
BLOCK = '''  # BEGIN AGENTIC ONLYOFFICE LAB
  handle /onlyoffice-test {
    redir /onlyoffice-test/ 302
  }
  handle /onlyoffice-test/* {
    reverse_proxy host.docker.internal:3212
  }
  handle_path /onlyoffice-engine/* {
    @private_onlyoffice path /example* /welcome* /admin* /info* /internal*
    respond @private_onlyoffice 404
    reverse_proxy host.docker.internal:8088 {
      header_up X-Forwarded-Host agenticclasspilot.com/onlyoffice-engine
      header_up X-Forwarded-Proto https
    }
  }
  # END AGENTIC ONLYOFFICE LAB

'''


def change(text, enable, lab='127.0.0.1:3212', docs='127.0.0.1:8088'):
    for address in (lab, docs):
        host, port = address.rsplit(':', 1)
        if not ipaddress.ip_address(host).is_private or not port.isdigit():
            raise ValueError('Only private container upstreams are permitted')
    if BEGIN in text or END in text:
        if text.count(BEGIN) != 1 or text.count(END) != 1:
            raise ValueError('Unexpected lab gateway markers; inspect before changing')
        start = text.rfind('\n', 0, text.index(BEGIN)) + 1
        end = text.index('\n', text.index(END)) + 1
        if text[end:end+1] == '\n':
            end += 1
        text = text[:start] + text[end:]
    if enable:
        anchor = '  handle /teacher {'
        if text.count(anchor) != 1:
            raise ValueError('Expected exactly one existing teacher route')
        block = BLOCK.replace('host.docker.internal:3212', lab).replace('host.docker.internal:8088', docs)
        text = text.replace(anchor, block + anchor, 1)
    return text


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['enable', 'disable'])
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    args.destination.write_text(change(args.source.read_text(), args.mode == 'enable', os.environ.get('LAB_UPSTREAM', '127.0.0.1:3212'), os.environ.get('DOCS_UPSTREAM', '127.0.0.1:8088')))
