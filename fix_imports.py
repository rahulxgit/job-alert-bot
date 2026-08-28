import re

with open('ai/evaluator.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = "import re\nfrom dateutil import parser\nfrom datetime import datetime\n" + text

with open('ai/evaluator.py', 'w', encoding='utf-8') as f:
    f.write(text)

