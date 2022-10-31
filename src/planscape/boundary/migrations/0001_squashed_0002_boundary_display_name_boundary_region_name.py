# Generated by Django 4.1.1 on 2022-10-30 22:55

import django.contrib.gis.db.models.fields
from django.db import migrations, models
import django.db.models.deletion
from typing import Tuple


class Migration(migrations.Migration):

    replaces = [('boundary', '0001_initial'), ('boundary', '0002_boundary_display_name_boundary_region_name')]

    initial = True

    dependencies:list[Tuple[str, str]]  = [
    ]

    operations = [
        migrations.CreateModel(
            name='Boundary',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('boundary_name', models.CharField(max_length=120)),
                ('display_name', models.CharField(max_length=120, null=True)),
                ('region_name', models.CharField(max_length=120, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='BoundaryDetails',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('geometry', django.contrib.gis.db.models.fields.MultiPolygonField(null=True, srid=4269)),
                ('objectid', models.BigIntegerField(null=True)),
                ('shape_name', models.CharField(max_length=120, null=True)),
                ('states', models.CharField(max_length=50, null=True)),
                ('hectares', models.FloatField(null=True)),
                ('acres', models.FloatField(null=True)),
                ('boundary', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='boundary.boundary')),
            ],
        ),
    ]
