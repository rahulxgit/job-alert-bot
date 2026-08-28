import re

with open('ai/evaluator.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = "try:\n    from zoneinfo import ZoneInfo\nexcept ImportError:\n    from backports.zoneinfo import ZoneInfo\n\nIST = ZoneInfo('Asia/Kolkata')\n\n" + text

with open('ai/evaluator.py', 'w', encoding='utf-8') as f:
    f.write(text)
