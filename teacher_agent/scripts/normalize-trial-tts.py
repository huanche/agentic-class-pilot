"""Normalize ordinary Chinese numeric spans without reinterpreting code or identifiers."""

import json
import re
import sys

from wetext import Normalizer


normalizer = Normalizer(lang="zh", operator="tn")
# Require a speech context: a common unit, counter or percentage suffix.
# Letter/digit identifiers and array brackets stay intact.
amount = re.compile(
    r"(?<![0-9A-Za-z_./+\[-])\d+(?:\.\d+)?\s*"
    r"(?:[%％]|(?:个)?字节|千米|公里|厘米|毫米|毫秒|分钟|秒|公斤|米|度|元|个|倍|页|项|次)"
)


def normalize(text):
    return amount.sub(lambda match: normalizer.normalize(match[0]), text) if re.search(r"[\u3400-\u9fff]", text) else text


texts = json.loads(sys.stdin.buffer.read())
result = [normalize(text) for text in texts]
sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
