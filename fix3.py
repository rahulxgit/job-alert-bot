import re

def fix():
    with open('ai/evaluator.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # replace the exact array without any fancy unicode
    new_signals = '    graduate_signals = [\n        "new grad", "fresher", "0-1 years", "0-1 yrs", "0-1 yr", "0 to 1", "0-2 years", "0-2 yrs", "0-2 yr", "0 to 2", "0 - 2", "0\ufffd2", "0\ufffd1", "0\uFFFD2", "0\uFFFD1", "up to 1 year", "1 year experience", "1+ years", "final-year", "2026 graduate", "graduate", "entry level", "entry-level",\n    ]'
    
    content = re.sub(r'    graduate_signals = \[.*?\]', new_signals, content, flags=re.DOTALL)
    
    # Also let's fix the req_match regex just in case
    content = re.sub(r'req_match = re.search\(r"\\b\(\[2-9\]\|1\[0-9\]\)\\.*?', 'req_match = re.search(r"\\\\b([2-9]|1[0-9])\\\\+?\\\\s*(?:\\\\+|to|-|\\\\ufffd|\\\\s)*\\\\s*(?:years?|yrs?)\\\\s*(?:of\\\\s*experience)?\\\\b", text_lower)', content)

    with open('ai/evaluator.py', 'w', encoding='utf-8') as f:
        f.write(content)

fix()
