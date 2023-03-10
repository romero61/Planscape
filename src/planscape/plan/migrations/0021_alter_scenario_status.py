# Generated by Django 4.1.3 on 2023-03-10 02:54

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('plan', '0020_alter_scenario_plan_alter_scenario_project'),
    ]

    operations = [
        migrations.AlterField(
            model_name='scenario',
            name='status',
            field=models.IntegerField(choices=[(0, 'Initialized'), (1, 'Pending'), (2, 'Processing'), (3, 'Success'), (4, 'Failed')], default=0),
        ),
    ]
