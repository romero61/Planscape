import json
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction
from base.condition_types import ConditionLevel, ConditionScoreType
from conditions.models import BaseCondition, Condition, ConditionRaster


class Command(BaseCommand):
    help = "Loads conditions from 'conditions.json' into the database."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--conditions-file",
            type=str,
            default=str(settings.DEFAULT_CONDITIONS_FILE),
        )

        parser.add_argument(
            "--dry-run",
            default=False,
            action="store_true",
            help="Configures if this is a dry-run. If true, no changes will be persisted.",
        )

    def handle(self, *args, **options):
        conditions_file = options["conditions_file"]
        path = Path(conditions_file)
        if not path.exists():
            self.stderr.write(f"Conditions file {conditions_file} does not exist")

        with open(conditions_file) as f:
            conditions = json.load(f)

            with transaction.atomic():
                metrics = self.get_metrics(conditions["regions"])
                self.stdout.write(f"Found {len(metrics)} metrics")

                for metric in metrics:
                    self.process_metric(metric)

                if options["dry_run"]:
                    transaction.set_rollback(True)

    def get_metrics(self, regions):
        regions = (region for region in regions)
        pillars = self.get_pillars_from_regions(regions)
        elements = self.get_elements_from_pillars(pillars)
        metrics = list(self.get_metrics_from_elements(elements))
        return metrics

    def get_pillars_from_regions(self, regions):
        for region in regions:
            pillars = region.pop("pillars")
            for pillar in pillars:
                yield {**region, **pillar}

    def get_elements_from_pillars(self, pillars):
        for pillar in pillars:
            elements = pillar.pop("elements")
            for element in elements:
                yield {**pillar, **element}

    def get_metrics_from_elements(self, elements):
        for element in elements:
            metrics = element.pop("metrics")
            for metric in metrics:
                yield {**element, **metric}

    def process_metric(self, metric):
        base_condition, bc_created = BaseCondition.objects.update_or_create(
            condition_name=metric["metric_name"],
            display_name=metric["display_name"],
            region_name=metric["region_name"],
            condition_level=ConditionLevel.METRIC,
        )

        condition, c_created = Condition.objects.update_or_create(
            condition_dataset=base_condition,
            raster_name=metric["raw_data_download_path"],
            condition_score_type=ConditionScoreType.CURRENT,
            is_raw=True,
        )

        # we are skipping registering raster datasources for now
        self.stdout.write(
            f"Processed {metric['region_name']}:{metric['metric_name']} - created base ?{bc_created} - created cond? {c_created}"
        )
