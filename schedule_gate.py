import json
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Amsterdam")

# Anchor the recurring sequence:
# 16 Sep 2026 08:00
# 17 Sep 2026 20:00
# 19 Sep 2026 08:00
# 20 Sep 2026 20:00
# ...every 36 hours thereafter.
ANCHOR = datetime(2026, 9, 16, 8, 0, tzinfo=TZ)


def scheduled_occurrence(cron, now):
    """Find the most recent occurrence of one of the workflow's daily UTC crons."""
    minute, hour, *calendar = cron.split()
    if calendar != ["*", "*", "*"]:
        raise ValueError(f"Expected a daily UTC schedule, got {cron!r}")
    now_utc = now.astimezone(timezone.utc)
    occurrence = now_utc.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    if occurrence > now_utc:
        occurrence -= timedelta(days=1)
    return occurrence.astimezone(TZ)


now = datetime.now(TZ)
candidate = now
event_path = os.environ.get("GITHUB_EVENT_PATH")
if event_path:
    with open(event_path) as event_file:
        candidate = scheduled_occurrence(json.load(event_file)["schedule"], now)

slot_number = round((candidate - ANCHOR) / timedelta(hours=36))
slot = ANCHOR + timedelta(hours=36 * slot_number)

should_run = (
    candidate.date() == slot.date()
    and candidate.hour == slot.hour
)
# A scheduled rerun can be days old and carries only the original cron expression.
if event_path and os.environ.get("GITHUB_RUN_ATTEMPT", "1") != "1":
    print("Skipping a repeated scheduled run. Use manual dispatch for an intentional search.")
    should_run = False

print(
    f"{'RUN' if should_run else 'SKIP'}: "
    f"started = {now:%d/%m/%Y %H:%M %Z}; "
    f"scheduled = {candidate:%d/%m/%Y %H:%M %Z}; "
    f"nearest 36h slot = {slot:%d/%m/%Y %H:%M %Z}"
)

github_output = os.environ.get("GITHUB_OUTPUT")

if github_output:
    with open(github_output, "a") as f:
        f.write(f"run={'true' if should_run else 'false'}\n")
