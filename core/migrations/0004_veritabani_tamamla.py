# Eksik kalmış sütunları tamamlar.
#
# 0002 yayımlanmadan önce iki kez yeniden yazıldı ve ara sürümlerinden biri canlı veritabanına
# kuruldu. Django o veritabanında 0002'yi "uygulandı" saydığı için sonraki sürümdeki
# `core_business.billing_day` sütunu hiç eklenmedi ve kurulum bu sütunu okurken durdu.
# Bu adım, veritabanı hangi ara sürümde kalmış olursa olsun aynı sonuca getirir: sütun yoksa ekler,
# varsa dokunmaz. Modellerin durumu değişmez (alanlar 0002 ve 0003'te zaten tanımlı).

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_uyelik_duzeltmeleri"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                'ALTER TABLE "core_business" ADD COLUMN IF NOT EXISTS '
                '"billing_day" smallint NULL CHECK ("billing_day" >= 0)',
                'ALTER TABLE "core_subscriptionpayment" ADD COLUMN IF NOT EXISTS '
                '"status_before" varchar(10) DEFAULT \'\' NOT NULL',
                'ALTER TABLE "core_subscriptionpayment" ALTER COLUMN "status_before" DROP DEFAULT',
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
