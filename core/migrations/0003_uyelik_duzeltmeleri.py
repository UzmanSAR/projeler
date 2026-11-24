# Ödemeye "önceki durum" alanı; üyelik bitişi elle yazılmaz.
#
# Sütun "yoksa ekle" biçiminde eklenir: bu adım yayımlanmadan önce aynı sütunu 0002 içinde taşıyan bir
# ara sürüm canlıya kurulmuş olabilir; o veritabanında sütun zaten vardır.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_uyelik_ve_geri_bildirim"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=[
                        'ALTER TABLE "core_subscriptionpayment" ADD COLUMN IF NOT EXISTS '
                        '"status_before" varchar(10) DEFAULT \'\' NOT NULL',
                        'ALTER TABLE "core_subscriptionpayment" ALTER COLUMN "status_before" DROP DEFAULT',
                    ],
                    reverse_sql='ALTER TABLE "core_subscriptionpayment" DROP COLUMN IF EXISTS "status_before"',
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="subscriptionpayment",
                    name="status_before",
                    field=models.CharField(blank=True, editable=False, max_length=10),
                ),
            ],
        ),
        migrations.AlterField(
            model_name="business",
            name="paid_until",
            field=models.DateField(
                blank=True, editable=False, null=True, verbose_name="üyelik bitişi"
            ),
        ),
    ]
