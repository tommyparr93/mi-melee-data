from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0048_prseason_graphic_video'),
    ]

    operations = [
        migrations.AddField(
            model_name='player',
            name='startgg_slug',
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
    ]
