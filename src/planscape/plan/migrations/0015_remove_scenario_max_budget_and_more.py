# Generated by Django 4.1.3 on 2023-02-20 04:55

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("plan", "0014_scenario_notes"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="scenario",
            name="max_budget",
        ),
        migrations.RemoveField(
            model_name="scenario",
            name="max_road_distance",
        ),
        migrations.RemoveField(
            model_name="scenario",
            name="max_slope",
        ),
        migrations.RemoveField(
            model_name="scenario",
            name="max_treatment_area_ratio",
        ),
    ]
