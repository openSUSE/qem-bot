try:
    from datetime import UTC
except ImportError:
    from datetime import timezone

    UTC = timezone.utc
