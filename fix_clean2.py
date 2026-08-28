import sys

with open('ai/evaluator.py', 'r', encoding='utf-8') as f:
    text = f.read()

# 1. return None, None
text = text.replace("    return max(candidates, key=lambda x: x[1])", "    return None, None")

# 2. walkin_date_conflict
old_conflict = '''                if not start_date and not end_date:
                    valid_date = wd
                elif start_date and end_date and start_date <= wd <= end_date:
                    valid_date = wd
                elif start_date and end_date:
                    valid_date = start_date
            except ValueError:
                pass
        elif start_date:
            valid_date = start_date'''

new_conflict = '''                if not start_date and not end_date:
                    valid_date = wd
                elif start_date and end_date and start_date <= wd <= end_date:
                    valid_date = wd
                elif start_date and wd == start_date:
                    valid_date = wd
                else:
                    valid_date = start_date
                    listing.walkin_date_conflict = True
            except ValueError:
                pass
        elif start_date:
            valid_date = start_date
            if raw_date and start_date.strftime("%Y-%m-%d") != raw_date:
                listing.walkin_date_conflict = True'''
text = text.replace(old_conflict, new_conflict)

# 3. Clean up the duplicate inline imports
text = text.replace("    import re\n    from dateutil import parser\n    from datetime import datetime\n", "")
text = text.replace("try:\n    from zoneinfo import ZoneInfo\nexcept ImportError:\n    from backports.zoneinfo import ZoneInfo\n\nIST = ZoneInfo(\"Asia/Kolkata\")", "IST = ZoneInfo(\"Asia/Kolkata\")")
text = text.replace("    import re\n", "")
with open('ai/evaluator.py', 'w', encoding='utf-8') as f:
    f.write(text)

