from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os

TZ = ZoneInfo("Europe/Amsterdam")

# Anchor the recurring sequence:
# 16 Sep 2026 08:00
# 17 Sep 2026 20:00
# 19 Sep 2026 08:00
# 20 Sep 2026 20:00
# ...every 36 hours thereafter.
ANCHOR = datetime(2026, 9, 16, 8, 0, tzinfo=TZ)

now = datetime.now(TZ)

elapsed_hours = (now - ANCHOR).total_seconds() / 3600

# GitHub scheduled jobs can start a few minutes late, so we identify
# the intended slot by local date/hour rather than requiring :00 exactly.
slot_number = round(elapsed_hours / 36)
slot = ANCHOR + timedelta(hours=36 * slot_number)

should_run = (
    now.date() == slot.date()
    and now.hour == slot.hour
)

print(
    f"{'RUN' if should_run else 'SKIP'}: "
    f"{now:%d/%m/%Y %H:%M %Z}; "
    f"nearest 36h slot = {slot:%d/%m/%Y %H:%M %Z}"
)

github_output = os.environ.get("GITHUB_OUTPUT")

if github_output:
    with open(github_output, "a") as f:
        f.write(f"run={'true' if should_run else 'false'}\n")
