import re
with open('ai/evaluator.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Replace any lingering ??? or mangled characters with a safe regex
text = re.sub(r'"0\ufffd1"', '"0-1"', text)
text = re.sub(r'"0\ufffd2"', '"0-2"', text)
text = re.sub(r'"0\?1"', '"0-1"', text)
text = re.sub(r'"0\?2"', '"0-2"', text)
text = text.replace('???', '')

# add back the safe list
new_signals = '    graduate_signals = [\n        "new grad", "fresher", "0-1 years", "0-1 yrs", "0-1 yr", "0 to 1", "0-2 years", "0-2 yrs", "0-2 yr", "0 to 2", "0 - 2", "0\ufffd2", "0\ufffd1", "up to 1 year", "1 year experience", "1+ years", "final-year", "2026 graduate", "graduate", "entry level", "entry-level",\n    ]'
text = re.sub(r'    graduate_signals = \[.*?\]', new_signals, text, flags=re.DOTALL)

with open('ai/evaluator.py', 'w', encoding='utf-8') as f:
    f.write(text)
