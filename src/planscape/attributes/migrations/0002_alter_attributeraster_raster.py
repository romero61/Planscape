# Generated by Django 4.1.11 on 2023-09-08 22:05

import django.contrib.gis.db.models.fields
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("attributes", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="attributeraster",
            name="raster",
            field=django.contrib.gis.db.models.fields.RasterField(null=True, srid=3857),
        ),
    ]
