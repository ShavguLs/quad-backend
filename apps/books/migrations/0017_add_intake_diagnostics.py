# Generated migration to add intake_diagnostics field to Book model

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("books", "0016_add_book_audit_log"),
    ]

    operations = [
        migrations.AddField(
            model_name="book",
            name="intake_diagnostics",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Diagnostic information about unsupported style fragments detected during import",
            ),
        ),
    ]
