"""Replace SaleProduct.recipe with a quantified, polymorphic link.

Renames ``recipe`` to ``link_recipe`` (so existing FKs survive verbatim
— every linked row keeps its target), adds ``link_product`` (FK to
SaleProduct itself, used for Pack/N → Loose-style chains),
``link_quantity`` (default 1) and ``link_unit`` (default "count"), then
a DB CheckConstraint that bans setting BOTH ``link_recipe`` and
``link_product`` on the same row. Both nullable means "unlinked",
exactly one set means "linked to that target", and neither/both
mismatches are rejected at the DB layer.

Migration is data-preserving: existing rows keep their recipe FK
(now stored in ``link_recipe``) and pick up the default quantity 1 /
unit count, which is exactly the semantics they always carried.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0019_saleproduct'),
    ]

    operations = [
        migrations.RenameField(
            model_name='saleproduct',
            old_name='recipe',
            new_name='link_recipe',
        ),
        migrations.AddField(
            model_name='saleproduct',
            name='link_product',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='linked_packs', to='stock.saleproduct',
                help_text='Another SaleProduct this one is a multiple of '
                          '(e.g. Pack/6 → Loose).'),
        ),
        migrations.AddField(
            model_name='saleproduct',
            name='link_quantity',
            field=models.DecimalField(
                decimal_places=3, default=1, max_digits=12,
                help_text='How many units / kg / g of the target.'),
        ),
        migrations.AddField(
            model_name='saleproduct',
            name='link_unit',
            field=models.CharField(
                choices=[
                    ('count', 'Units (count)'),
                    ('weight_kg', 'Kilograms'),
                    ('weight_g', 'Grams'),
                ],
                default='count', max_length=12),
        ),
        migrations.AddConstraint(
            model_name='saleproduct',
            constraint=models.CheckConstraint(
                check=models.Q(('link_recipe__isnull', True)) | models.Q(
                    ('link_product__isnull', True)),
                name='saleproduct_link_recipe_xor_product',
            ),
        ),
    ]
