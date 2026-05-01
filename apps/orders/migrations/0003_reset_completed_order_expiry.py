from datetime import timedelta

from django.db import migrations
from django.utils import timezone


def reset_completed_order_expiry(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    expiry_date = timezone.now() + timedelta(days=180)
    Order.objects.filter(status="COMPLETED").update(expires_at=expiry_date)


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0002_add_expires_at_to_order"),
    ]

    operations = [
        migrations.RunPython(reset_completed_order_expiry, migrations.RunPython.noop),
    ]
