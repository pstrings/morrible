import re
import datetime
import calendar

DAY_MAP = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6
}


def parse_duration_to_seconds(duration_str: str) -> int | None:
    """Parses a duration string (e.g., 1h30m, 10m, 2d) into total seconds."""
    clean = duration_str.strip().lower()
    pattern = re.compile(r"^(\d+[smhdw]\s*)+$")
    if not pattern.match(clean):
        return None

    match_units = re.findall(r"(\d+)([smhdw])", clean)
    if not match_units:
        return None

    total_seconds = 0
    for amount_str, unit in match_units:
        amount = int(amount_str)
        if unit == "s":
            total_seconds += amount
        elif unit == "m":
            total_seconds += amount * 60
        elif unit == "h":
            total_seconds += amount * 3600
        elif unit == "d":
            total_seconds += amount * 86400
        elif unit == "w":
            total_seconds += amount * 604800

    return total_seconds if total_seconds > 0 else None


def parse_time_of_day(time_str: str) -> datetime.time | None:
    """Parses time strings like '10:00', '10am', '3:30pm', '17:00'."""
    clean_str = time_str.strip().lower()

    # Check 12-hour format: 3pm, 3:30pm, 10am, 10:45am
    m12 = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$", clean_str)
    if m12:
        hour = int(m12.group(1))
        minute = int(m12.group(2)) if m12.group(2) else 0
        meridiem = m12.group(3)

        if hour < 1 or hour > 12 or minute < 0 or minute > 59:
            return None

        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0

        return datetime.time(hour=hour, minute=minute)

    # Check 24-hour format: 15:30, 09:00, 9:00
    m24 = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", clean_str)
    if m24:
        hour = int(m24.group(1))
        minute = int(m24.group(2))
        second = int(m24.group(3)) if m24.group(3) else 0
        if 0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59:
            return datetime.time(hour=hour, minute=minute, second=second)

    return None


def parse_days_list(days_str: str) -> list[int] | None:
    """Parses a string containing days like 'monday and wednesday', 'weekdays', 'sat, sun'."""
    clean = days_str.lower().strip()
    if clean in ["everyday", "daily", "day", "days"]:
        return list(range(7))
    if clean in ["weekday", "weekdays"]:
        return [0, 1, 2, 3, 4]
    if clean in ["weekend", "weekends"]:
        return [5, 6]

    tokens = re.split(r"[\s,;&]+|and|or", clean)
    found_days = set()
    for tok in tokens:
        tok = tok.strip()
        if not tok:
            continue
        if tok in DAY_MAP:
            found_days.add(DAY_MAP[tok])

    if found_days:
        return sorted(list(found_days))
    return None


def get_next_occurrence_for_days_and_time(
    days: list[int], target_time: datetime.time, now: datetime.datetime
) -> datetime.datetime:
    """Finds the next datetime matching one of the given days and target time."""
    candidate_date = now.date()

    for day_offset in range(8):
        check_date = candidate_date + datetime.timedelta(days=day_offset)
        if check_date.weekday() in days:
            candidate_dt = datetime.datetime.combine(check_date, target_time, tzinfo=now.tzinfo)
            if candidate_dt > now:
                return candidate_dt

    check_date = candidate_date + datetime.timedelta(days=7)
    return datetime.datetime.combine(check_date, target_time, tzinfo=now.tzinfo)


def get_next_trigger_from_rule(recurrence_rule: str, now: datetime.datetime) -> datetime.datetime | None:
    """Calculates the next trigger datetime based on a recurrence_rule string."""
    if not recurrence_rule:
        return None

    if recurrence_rule.startswith("INTERVAL:"):
        try:
            seconds = int(recurrence_rule.split(":")[1])
            next_t = now + datetime.timedelta(seconds=seconds)
            while next_t <= now:
                next_t += datetime.timedelta(seconds=seconds)
            return next_t
        except Exception:
            return None

    if recurrence_rule.startswith("DAYS:"):
        try:
            parts = recurrence_rule.split("|TIME:")
            days_part = parts[0].replace("DAYS:", "")
            days = [int(d) for d in days_part.split(",") if d.isdigit()]

            time_parts = [int(t) for t in parts[1].split(":")]
            target_time = datetime.time(hour=time_parts[0], minute=time_parts[1], second=time_parts[2] if len(time_parts) > 2 else 0)

            return get_next_occurrence_for_days_and_time(days, target_time, now)
        except Exception:
            return None

    return None


def parse_reminder_input(
    input_str: str,
    is_continuous_override: bool = False,
    now: datetime.datetime | None = None
) -> tuple[datetime.datetime | None, bool, str | None, int, str]:
    """
    Parses arbitrary reminder timing input.
    Returns tuple: (next_trigger, is_continuous, recurrence_rule, duration_seconds, human_description)
    """
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)

    raw = input_str.strip().lower()

    # Check repeating prefix: "every ", "repeat ", "everyday", "daily"
    is_repeat_keyword = False
    if raw.startswith("every ") or raw.startswith("repeat ") or raw.startswith("everyday") or raw.startswith("daily"):
        is_repeat_keyword = True
        body = re.sub(r"^(every|repeat)\s*", "", raw).strip()
        if body == "day" or body == "days":
            body = "everyday"

        # Check interval repeat e.g. "every 10m"
        interval_sec = parse_duration_to_seconds(body)
        if interval_sec is not None:
            next_t = now + datetime.timedelta(seconds=interval_sec)
            rule = f"INTERVAL:{interval_sec}"
            return next_t, True, rule, interval_sec, f"every {body}"

        # Check day-of-week / time repeat
        time_part = "09:00"
        days_part = body

        if " at " in body:
            dp, tp = body.split(" at ", 1)
            days_part = dp.strip()
            time_part = tp.strip()

        days_list = parse_days_list(days_part)
        parsed_time = parse_time_of_day(time_part)

        if days_list and parsed_time:
            next_t = get_next_occurrence_for_days_and_time(days_list, parsed_time, now)
            rule = f"DAYS:{','.join(map(str, days_list))}|TIME:{parsed_time.strftime('%H:%M:%S')}"

            rev_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
            if len(days_list) == 7:
                days_desc = "day"
            elif days_list == [0, 1, 2, 3, 4]:
                days_desc = "weekday"
            elif days_list == [5, 6]:
                days_desc = "weekend day"
            else:
                days_desc = ", ".join(rev_map[d] for d in days_list)

            time_desc = parsed_time.strftime("%I:%M %p").lstrip("0")
            human_desc = f"every {days_desc} at {time_desc}"
            return next_t, True, rule, 0, human_desc

    # Simple relative duration e.g. "10m", "2h", "1d12h"
    dur_sec = parse_duration_to_seconds(raw)
    if dur_sec is not None:
        next_t = now + datetime.timedelta(seconds=dur_sec)
        is_cont = is_continuous_override
        rule = f"INTERVAL:{dur_sec}" if is_cont else None
        desc = f"every {raw}" if is_cont else f"in {raw}"
        return next_t, is_cont, rule, dur_sec, desc

    # Absolute date/time or day-of-week one-time e.g. "tomorrow at 3pm", "today at 8pm", "monday at 10am", "2026-08-01 15:30"
    if "tomorrow" in raw or "today" in raw:
        target_date = now.date() if "today" in raw else now.date() + datetime.timedelta(days=1)
        time_str = "09:00"
        if " at " in raw:
            time_str = raw.split(" at ", 1)[1]
        elif len(raw.split()) > 1:
            time_str = raw.split()[-1]

        parsed_t = parse_time_of_day(time_str)
        if parsed_t:
            cand_dt = datetime.datetime.combine(target_date, parsed_t, tzinfo=now.tzinfo)
            if cand_dt <= now and "today" in raw:
                cand_dt += datetime.timedelta(days=1)
            dur = int((cand_dt - now).total_seconds())
            is_cont = is_continuous_override
            rule = f"INTERVAL:{dur}" if (is_cont and dur > 0) else None
            return cand_dt, is_cont, rule, dur, f"at {cand_dt.strftime('%b %d, %Y %I:%M %p')}"

    for day_name, day_num in DAY_MAP.items():
        if raw.startswith(day_name) or raw.startswith(f"next {day_name}"):
            time_str = "09:00"
            if " at " in raw:
                time_str = raw.split(" at ", 1)[1]
            elif len(raw.split()) > 1:
                time_str = raw.split()[-1]

            parsed_t = parse_time_of_day(time_str)
            if parsed_t:
                next_t = get_next_occurrence_for_days_and_time([day_num], parsed_t, now)
                dur = int((next_t - now).total_seconds())
                is_cont = is_continuous_override
                rule = f"INTERVAL:{dur}" if (is_cont and dur > 0) else None
                return next_t, is_cont, rule, dur, f"on {next_t.strftime('%A at %I:%M %p')}"

    # Check YYYY-MM-DD HH:MM
    m_iso = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{1,2}:\d{2}(?::\d{2})?))?$", raw)
    if m_iso:
        try:
            year, month, day = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
            t_str = m_iso.group(4) if m_iso.group(4) else "09:00"
            p_time = parse_time_of_day(t_str)
            if p_time:
                cand_dt = datetime.datetime(year, month, day, p_time.hour, p_time.minute, p_time.second, tzinfo=now.tzinfo)
                if cand_dt > now:
                    dur = int((cand_dt - now).total_seconds())
                    is_cont = is_continuous_override
                    rule = f"INTERVAL:{dur}" if (is_cont and dur > 0) else None
                    return cand_dt, is_cont, rule, dur, f"on {cand_dt.strftime('%b %d, %Y %I:%M %p')}"
        except ValueError:
            pass

    return None, False, None, 0, ""
