# Generated by Django 4.2 on 2023-10-02 23:47

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0032_prseason_is_active'),
    ]

    operations = [
        migrations.AlterField(
            model_name='set',
            name='tournament',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='main.tournament'),
        ),
    ]