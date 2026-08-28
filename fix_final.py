import re

def fix():
    with open('ai/evaluator.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 1. Modify the return max(candidates...) to return None, None
    content = content.replace("    return max(candidates, key=lambda x: x[1])", "    return None, None")
    
    # 2. Add walkin_date_conflict flag in _apply_verdict
    old_conflict = '''                elif start_date and end_date:
                    valid_date = start_date'''
    new_conflict = '''                elif start_date and end_date:
                    valid_date = start_date
                    listing.walkin_date_conflict = True'''
    content = content.replace(old_conflict, new_conflict)
    
    # What if only start_date exists and LLM doesn't match?
    old_elif = '''        elif start_date:
            valid_date = start_date'''
    new_elif = '''        elif start_date:
            valid_date = start_date
            if raw_date and start_date.strftime("%Y-%m-%d") != raw_date:
                listing.walkin_date_conflict = True'''
    content = content.replace(old_elif, new_elif)

    # Note: What if raw_date exists, and start_date exists but end_date doesn't, we handled it inside the try block:
    old_try = '''                if not start_date and not end_date:
                    valid_date = wd
                elif start_date and end_date and start_date <= wd <= end_date:
                    valid_date = wd
                elif start_date and end_date:
                    valid_date = start_date'''
    new_try = '''                if not start_date and not end_date:
                    valid_date = wd
                elif start_date and end_date and start_date <= wd <= end_date:
                    valid_date = wd
                elif start_date and wd == start_date:
                    valid_date = start_date
                else:
                    valid_date = start_date
                    listing.walkin_date_conflict = True'''
    content = content.replace(old_try, new_try)

    # 3. Clean up duplicate imports at the top
    # The user says "Remove duplicate module-level imports of ZoneInfo, datetime, date, dateutil.parser, re"
    # Let's just remove the ones inside the functions.
    content = re.sub(r'\n\s*import re\n', '\n', content)
    content = re.sub(r'\n\s*from dateutil import parser\n', '\n', content)
    content = re.sub(r'\n\s*from datetime import datetime\n', '\n', content)

    # Also there is a duplicate zoneinfo block
    content = re.sub(r'(?ms)try:\n    from zoneinfo import ZoneInfo\nexcept ImportError:\n    from backports.zoneinfo import ZoneInfo\n.*?IST = ZoneInfo\("Asia/Kolkata"\)', '', content, count=1)
    
    with open('ai/evaluator.py', 'w', encoding='utf-8') as f:
        f.write(content)

fix()
