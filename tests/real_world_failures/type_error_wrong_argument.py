def send_email(to_address, subject, *, retry_count=3):
    return f"queued:{to_address}:{subject}:{retry_count}"


print(send_email("ops@example.com", "Backup failed", True))
