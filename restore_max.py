import sys

with open('ai/evaluator.py', 'r', encoding='utf-8') as f:
    text = f.read()

# restore the max(candidates)
text = text.replace("    return None, None\n\ndef keyword_prefilter_score", "    return max(candidates, key=lambda x: x[1])\n\ndef keyword_prefilter_score")

with open('ai/evaluator.py', 'w', encoding='utf-8') as f:
    f.write(text)
