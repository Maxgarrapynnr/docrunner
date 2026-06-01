"""
docrunner/admin.py

Admin registrations for the single owner. The Secret admin is deliberately
write-only for the value: you can set a new plaintext, but the stored ciphertext
is never displayed back — matching the "never log/display plaintext" rule.

Bindings can be created and managed here until a dedicated binding UI exists;
the webhook token/secret are shown read-only after creation so they can be
copied into the calling system.
"""
from django import forms
from django.contrib import admin

from docrunner.models import (
    Template, Binding, Run, Output, Delivery, Secret,
)


# ──────────────────────────────────────────────
# Secret — write-only plaintext entry
# ──────────────────────────────────────────────
class SecretForm(forms.ModelForm):
    new_value = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False),
        help_text="Enter to set/replace the value. Leave blank to keep current.",
    )

    class Meta:
        model = Secret
        fields = ["name", "description"]

    def save(self, commit=True):
        secret = super().save(commit=False)
        plaintext = self.cleaned_data.get("new_value")
        if plaintext:
            secret.set_value(plaintext)
        elif not secret.pk and not getattr(secret, "_ciphertext", None):
            raise forms.ValidationError("A value is required for a new secret.")
        if commit:
            secret.save()
        return secret


@admin.register(Secret)
class SecretAdmin(admin.ModelAdmin):
    form = SecretForm
    list_display = ["name", "description", "updated_at"]
    search_fields = ["name"]
    readonly_fields = ["created_at", "updated_at"]
    # The encrypted value column is never exposed in the admin.


# ──────────────────────────────────────────────
# Binding
# ──────────────────────────────────────────────
@admin.register(Binding)
class BindingAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "template", "output_format", "enabled", "created_at"]
    list_filter = ["kind", "enabled", "output_format"]
    search_fields = ["name"]
    readonly_fields = ["webhook_token", "webhook_secret", "created_at"]
    fieldsets = (
        (None, {"fields": ("template", "name", "kind", "enabled")}),
        ("Output", {"fields": ("output_format", "filename_field", "missing_policy")}),
        ("Configuration", {"fields": ("config",)}),
        ("Delivery", {"fields": ("delivery_kind", "delivery_config")}),
        ("Webhook (read-only, generated on save)", {
            "fields": ("webhook_token", "webhook_secret"),
            "classes": ("collapse",),
        }),
    )


# ──────────────────────────────────────────────
# Template / Run / Output / Delivery (mostly read-only views)
# ──────────────────────────────────────────────
@admin.register(Template)
class TemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "fmt", "created_at"]
    list_filter = ["fmt"]
    search_fields = ["name"]
    readonly_fields = ["schema", "created_at", "updated_at"]


class OutputInline(admin.TabularInline):
    model = Output
    extra = 0
    readonly_fields = ["filename", "fmt", "size_bytes", "record_index", "is_archive", "created_at"]
    can_delete = False


@admin.register(Run)
class RunAdmin(admin.ModelAdmin):
    list_display = ["id", "template", "status", "trigger", "record_count", "output_format", "queued_at"]
    list_filter = ["status", "trigger", "output_format"]
    search_fields = ["template__name"]
    readonly_fields = [
        "template", "binding", "trigger", "status", "output_format",
        "input_records", "record_count", "report",
        "queued_at", "started_at", "finished_at", "duration_ms",
    ]
    inlines = [OutputInline]


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = ["id", "kind", "status", "attempts", "created_at", "sent_at"]
    list_filter = ["kind", "status"]
    readonly_fields = ["output", "kind", "target", "attempts", "last_error", "created_at", "sent_at"]
