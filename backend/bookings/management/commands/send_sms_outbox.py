from django.core.management.base import BaseCommand, CommandError

from bookings.sms import SmsProviderError, process_sms_outbox


class Command(BaseCommand):
    help = "Process queued booking SMS messages through the configured provider."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit < 1 or limit > 1000:
            raise CommandError("--limit must be between 1 and 1000.")
        try:
            result = process_sms_outbox(limit=limit)
        except SmsProviderError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            "SMS outbox processed: "
            f"accepted={result['accepted']} failed={result['failed']}"
        )
