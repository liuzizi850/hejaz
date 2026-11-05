# Generated manually. Depends on 0003_event_chain_recording.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app_automation', '0003_event_chain_recording'),
    ]

    operations = [
        migrations.AddField(
            model_name='apptestexecution',
            name='mismatch_current_url',
            field=models.CharField(blank=True, default='', max_length=500, null=True, verbose_name='不匹配当前界面'),
        ),
        migrations.AddField(
            model_name='apptestexecution',
            name='mismatch_expected_url',
            field=models.CharField(blank=True, default='', max_length=500, null=True, verbose_name='不匹配开始界面'),
        ),
    ]
