import time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from wallets.tasks.execute_withdrawals import execute_due_withdrawals


class Command(BaseCommand):
    help = "Run due scheduled withdrawals once or in a loop."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Max due withdrawals to process per run",
        )
        parser.add_argument(
            "--loop",
            action="store_true",
            help="Run continuously with sleep intervals between cycles",
        )
        parser.add_argument(
            "--sleep-seconds",
            type=float,
            default=2.0,
            help="Sleep interval for loop mode",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        run_loop = options["loop"]
        sleep_seconds = options["sleep_seconds"]

        if limit <= 0:
            raise CommandError("--limit must be greater than zero")

        if sleep_seconds < 0:
            raise CommandError("--sleep-seconds must be >= 0")

        while True:
            summary = execute_due_withdrawals(limit=limit, now=timezone.now())
            self.stdout.write(
                self.style.SUCCESS(
                    (
                        "withdrawal executor run completed: "
                        f"processed={summary['processed']} succeeded={summary['succeeded']} "
                        f"failed={summary['failed']} insufficient_funds={summary['insufficient_funds']} "
                        f"reconciliation_queued={summary.get('reconciliation_queued', 0)}"
                    )
                )
            )

            if not run_loop:
                break

            time.sleep(sleep_seconds)
