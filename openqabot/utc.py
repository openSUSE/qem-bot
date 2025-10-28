try:
    from datetime import UTC
except ImportError:
    from datetime.timezone import utc

    UTC = utc
