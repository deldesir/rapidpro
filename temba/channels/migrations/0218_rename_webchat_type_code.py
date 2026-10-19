from django.db import migrations


def rename_webchat_type_code(apps, schema_editor):
    Channel = apps.get_model("channels", "Channel")

    num_updated = Channel.objects.filter(channel_type="WCH").update(channel_type="CHP")
    if num_updated:
        print(f"Renamed type code of {num_updated} webchat channels")


class Migration(migrations.Migration):
    dependencies = [("channels", "0217_audit_fields_cleanup")]

    operations = [migrations.RunPython(rename_webchat_type_code, migrations.RunPython.noop)]
