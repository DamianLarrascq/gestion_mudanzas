# Generated manually — eliminar FotoInventario (modelo no utilizado)
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0014_camion_en_taller'),
    ]

    operations = [
        migrations.DeleteModel(
            name='FotoInventario',
        ),
    ]
