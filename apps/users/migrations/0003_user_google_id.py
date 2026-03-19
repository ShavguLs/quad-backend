from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0002_add_profile_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="google_id",
            field=models.CharField(blank=True, max_length=255, null=True, unique=True),
        ),
    ]
