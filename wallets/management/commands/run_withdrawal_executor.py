import logging
import random
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from wallets.tasks.execute_withdrawals import execute_due_withdrawals
from wallets.tasks.reconcile_withdrawals import reconcile_withdrawals

logger = logging.getLogger(__name__)


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
            default=None,
            help="Base sleep interval for loop mode (defaults to WORKER_LOOP_INTERVAL)",
        )
        parser.add_argument(
            "--reconcile-limit",
            type=int,
            default=100,
            help="Max reconciliation tasks to process per run",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        run_loop = options["loop"]
        reconcile_limit = options["reconcile_limit"]
        configured_interval = settings.WORKER_LOOP_INTERVAL
        base_interval = (
            configured_interval
            if options["sleep_seconds"] is None
            else options["sleep_seconds"]
        )
        startup_jitter_max = settings.WORKER_STARTUP_JITTER_MAX
        loop_jitter_max = settings.WORKER_LOOP_JITTER_MAX

        if limit <= 0:
            raise CommandError("--limit must be greater than zero")

        if base_interval < 0:
            raise CommandError("--sleep-seconds must be >= 0")
        if reconcile_limit <= 0:
            raise CommandError("--reconcile-limit must be greater than zero")

        if run_loop and startup_jitter_max > 0:
            startup_wait = random.uniform(0, startup_jitter_max)
            logger.info(
                "event=worker_startup_jitter worker_role=executor startup_delay_ms=%s",
                int(startup_wait * 1000),
            )
            time.sleep(startup_wait)

        while True:
            now = timezone.now()
            summary = execute_due_withdrawals(limit=limit, now=now)
            reconcile_summary = reconcile_withdrawals(limit=reconcile_limit, now=now)
            self.stdout.write(
                self.style.SUCCESS(
                    (
                        "withdrawal executor run completed: "
                        f"processed={summary['processed']} succeeded={summary['succeeded']} "
                        f"failed={summary['failed']} insufficient_funds={summary['insufficient_funds']} "
                        f"reconciliation_queued={summary.get('reconciliation_queued', 0)} "
                        f"unknown={summary.get('unknown', 0)} "
                        f"reconciled_success={reconcile_summary['resolved_success']} "
                        f"reconciled_failure={reconcile_summary['resolved_failure']}"
                    )
                )
            )

            if not run_loop:
                break

            jitter = random.uniform(0, loop_jitter_max) if loop_jitter_max > 0 else 0.0
            sleep_seconds = max(0.0, base_interval + jitter)
            time.sleep(sleep_seconds)
