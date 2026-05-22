"""Replace Recipe.role / role_is_manual with sold_as_product / is_sold_manual.

The old single-axis "role" couldn't represent a recipe that's both used as a
component AND sold standalone. The new pair splits those concerns:

- sold_as_product (stored bool, defaulted from references)
- is_used_as_component (live-derived from RecipeLine.sub_recipe; not stored)

Migration order: add the new columns, port any existing manual override
(role==final_product → sold; role==component → not sold; non-manual rows
default by structure), then drop the old columns. Reverse rebuilds the
old single-axis role from sold_as_product so a backwards migration is
lossless for the bits that map cleanly.
"""
from django.db import migrations, models


def _port_role_to_sold(apps, schema_editor):
    Recipe = apps.get_model("stock", "Recipe")
    RecipeLine = apps.get_model("stock", "RecipeLine")
    referenced = set(
        RecipeLine.objects
        .filter(sub_recipe__isnull=False)
        .values_list("sub_recipe_id", flat=True))
    for r in Recipe.objects.all():
        is_referenced = r.pk in referenced
        if r.role_is_manual:
            # Preserve operator intent: a recipe they pinned as final
            # is sold; one they pinned as component is not.
            r.sold_as_product = (r.role == "final_product")
            r.is_sold_manual = True
        else:
            r.sold_as_product = not is_referenced
            r.is_sold_manual = False
        r.save(update_fields=["sold_as_product", "is_sold_manual"])


def _port_sold_to_role(apps, schema_editor):
    Recipe = apps.get_model("stock", "Recipe")
    for r in Recipe.objects.all():
        r.role = "final_product" if r.sold_as_product else "component"
        r.role_is_manual = r.is_sold_manual
        r.save(update_fields=["role", "role_is_manual"])


class Migration(migrations.Migration):

    dependencies = [
        ("stock", "0011_recipe_role_recipe_role_is_manual"),
    ]

    operations = [
        migrations.AddField(
            model_name="recipe",
            name="sold_as_product",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="recipe",
            name="is_sold_manual",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(_port_role_to_sold, _port_sold_to_role),
        migrations.RemoveField(
            model_name="recipe",
            name="role",
        ),
        migrations.RemoveField(
            model_name="recipe",
            name="role_is_manual",
        ),
    ]
