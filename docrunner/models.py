"""
docrunner/models.py

The single source of truth every other module imports from: tasks.py,
deliveries.py, and datasources.py all `from docrunner.models import ...`.

Single-owner deployment: no User/owner foreign keys anywhere. The magic-link
login is a gate, not a tenancy boundary.

See DocRunner-data-model.md for the design rationale behind each model.
"""
import secrets as pysecrets
import uuid

from django.conf import settings
from django.db import models
from cryptography.fernet import Fernet


# ──────────────────────────────────────────────
# Enumerations
# ──────────────────────────────────────────────
class TemplateFormat(models.TextChoices):
    DOCX = "docx", "Word (.docx)"
    XLSX = "xlsx", "Excel (.xlsx)"


class OutputFormat(models.TextChoices):
    DOCX = "docx", "Word (.docx)"
    XLSX = "xlsx", "Excel (.xlsx)"
    PDF = "pdf", "PDF"


class BindingKind(models.TextChoices):
    FORM = "form", "Manual form"
    UPLOAD = "upload", "File upload (JSON/CSV)"
    WEBHOOK = "webhook", "Inbound webhook"
    PULL = "pull", "Scheduled pull"


class TriggerType(models.TextChoices):
    ON_DEMAND = "on_demand", "On demand"
    SCHEDULED = "scheduled", "Scheduled"
    WEBHOOK = "webhook", "Webhook"


class RunStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    SUCCESS = "success", "Success"
    PARTIAL = "partial", "Partial (some records failed)"
    FAILED = "failed", "Failed"


class MissingPolicy(models.TextChoices):
    ERROR = "error", "Error on missing field"
    BLANK = "blank", "Fill missing field blank"


class DeliveryKind(models.TextChoices):
    EMAIL = "email", "Email"
    WEBHOOK = "webhook", "Webhook callback"
    # OBJECT_STORAGE deferred to post-v1


class DeliveryStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"


# ──────────────────────────────────────────────
# Template
# ──────────────────────────────────────────────
class Template(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    fmt = models.CharField(max_length=8, choices=TemplateFormat.choices)
    file = models.FileField(upload_to="templates/")

    # Extracted at upload by services/extract.py. Shape documented in data-model §3.1.
    schema = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.fmt})"

    @property
    def placeholder_names(self) -> set[str]:
        """Flat set of every top-level placeholder, for validation."""
        return {f["name"] for f in self.schema.get("fields", [])}


# ──────────────────────────────────────────────
# Binding
# ──────────────────────────────────────────────
class Binding(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    template = models.ForeignKey(
        Template, related_name="bindings", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=12, choices=BindingKind.choices)

    output_format = models.CharField(
        max_length=8, choices=OutputFormat.choices, default=OutputFormat.PDF
    )
    filename_field = models.CharField(max_length=100, blank=True)
    missing_policy = models.CharField(
        max_length=8, choices=MissingPolicy.choices, default=MissingPolicy.ERROR
    )

    # Kind-specific config (examples in data-model §3.2).
    config = models.JSONField(default=dict, blank=True)

    # Webhook bindings only.
    webhook_token = models.CharField(max_length=64, blank=True, db_index=True)
    webhook_secret = models.CharField(max_length=128, blank=True)

    # Optional default delivery for runs from this binding.
    delivery_kind = models.CharField(
        max_length=12, choices=DeliveryKind.choices, blank=True
    )
    delivery_config = models.JSONField(default=dict, blank=True)

    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        # Mint token/secret the first time a webhook binding is saved.
        if self.kind == BindingKind.WEBHOOK and not self.webhook_token:
            self.webhook_token = pysecrets.token_urlsafe(32)
            self.webhook_secret = pysecrets.token_urlsafe(48)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} [{self.kind}] -> {self.template.name}"


# ──────────────────────────────────────────────
# Run
# ──────────────────────────────────────────────
class Run(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    template = models.ForeignKey(Template, related_name="runs", on_delete=models.CASCADE)
    binding = models.ForeignKey(
        Binding, related_name="runs", null=True, blank=True, on_delete=models.SET_NULL
    )

    trigger = models.CharField(max_length=12, choices=TriggerType.choices)
    status = models.CharField(
        max_length=12, choices=RunStatus.choices, default=RunStatus.QUEUED
    )
    output_format = models.CharField(max_length=8, choices=OutputFormat.choices)

    # Always a list of record dicts (len 1 == single).
    input_records = models.JSONField(default=list)
    record_count = models.PositiveIntegerField(default=0)

    # Validation + execution report (shape in data-model §3.3).
    report = models.JSONField(default=dict, blank=True)

    queued_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-queued_at"]
        indexes = [models.Index(fields=["status", "-queued_at"])]

    def __str__(self):
        return f"Run {self.id} [{self.status}] {self.template.name}"


# ──────────────────────────────────────────────
# Output
# ──────────────────────────────────────────────
class Output(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(Run, related_name="outputs", on_delete=models.CASCADE)

    file = models.FileField(upload_to="outputs/%Y/%m/")
    filename = models.CharField(max_length=255)
    fmt = models.CharField(max_length=8, choices=OutputFormat.choices)
    size_bytes = models.PositiveIntegerField(default=0)

    record_index = models.PositiveIntegerField(null=True, blank=True)
    is_archive = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["record_index"]

    def __str__(self):
        return self.filename


# ──────────────────────────────────────────────
# Delivery
# ──────────────────────────────────────────────
class Delivery(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    output = models.ForeignKey(Output, related_name="deliveries", on_delete=models.CASCADE)

    kind = models.CharField(max_length=12, choices=DeliveryKind.choices)
    target = models.JSONField(default=dict)

    status = models.CharField(
        max_length=12, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.kind} -> {self.status}"


# ──────────────────────────────────────────────
# Secret
# ──────────────────────────────────────────────
class Secret(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True)
    _ciphertext = models.BinaryField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def set_value(self, plaintext: str) -> None:
        f = Fernet(settings.ENCRYPTION_KEY)
        self._ciphertext = f.encrypt(plaintext.encode())

    @property
    def value(self) -> str:
        f = Fernet(settings.ENCRYPTION_KEY)
        return f.decrypt(bytes(self._ciphertext)).decode()

    def __str__(self):
        return self.name
