# Generated by Django 3.0.2 on 2020-04-03 17:32

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Plan', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='block',
            name='class_index',
            field=models.CharField(blank=True, default=None, max_length=1, null=True),
        ),
    ]
