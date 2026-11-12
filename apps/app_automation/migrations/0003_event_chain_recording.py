# Generated manually — makemigrations blocked (venv missing celery after pymysql install)

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('app_automation', '0002_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='apptestcase',
            name='event_chain',
            field=models.JSONField(blank=True, default=dict, verbose_name='事件链'),
        ),
        migrations.AddField(
            model_name='apptestcase',
            name='start_screen',
            field=models.CharField(blank=True, default='', max_length=500, verbose_name='开始界面截图'),
        ),
        migrations.AddField(
            model_name='apptestexecution',
            name='result_bundle_path',
            field=models.CharField(blank=True, default='', max_length=500, verbose_name='事件链结果包路径'),
        ),
        migrations.CreateModel(
            name='AppRecordingSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('recording', '录制中'), ('interrupted', '已中断'), ('stopped', '已停止')], default='recording', max_length=20)),
                ('steps', models.JSONField(blank=True, default=list)),
                ('start_screen', models.CharField(blank=True, default='', max_length=500)),
                ('screen', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('device', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='recording_sessions', to='app_automation.appdevice')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='app_recording_sessions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'app_recording_sessions',
                'ordering': ['-created_at'],
            },
        ),
    ]
