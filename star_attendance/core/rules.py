def parse_time_str(value):
    parts = value.split(":")
    hour = int(parts[0]) if parts[0] else 0
    minute = int(parts[1]) if len(parts) > 1 else 0
    return hour, minute


def build_day_time(now, value):
    hour, minute = parse_time_str(value)
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def check_in_rules(options, now):
    """
    Returns (allowed, cutoff_time)
    Rules disabled.
    """
    return True, None


def check_out_rules(options, now, last_in_time):
    """
    Returns (allowed, cutoff_time)
    Rules disabled.
    """
    return True, None
