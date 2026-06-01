"""
docrunner/datasources.py

The front of the pipeline. Turns any trigger's raw input — a submitted form, an
uploaded/posted JSON object or array, a CSV, or a scheduled pull — into a
normalized `list[dict]` of records, then creates a QUEUED Run and enqueues the
worker.

Every path converges on `create_run(...)`, so the worker (tasks.run_generation)
only ever sees one shape: Run.input_records as a list of dicts (len 1 == single).

Nothing here generates documents; it only normalizes input and hands off.
"""
import csv
import io
import json

import requests
from django.db import transaction
from django_q.tasks import async_task

from docrunner.models import (
    Run, Template, Binding,
    TriggerType, RunStatus, OutputFormat, BindingKind, Secret,
)

MAX_RECORDS = 5000          # guardrail against a runaway batch
PULL_TIMEOUT = 30


# ──────────────────────────────────────────────
# Public: one entry per trigger type
# ──────────────────────────────────────────────
def run_from_form(template: Template, form_data: dict, *,
                  output_format: str | None = None, binding: Binding | None = None) -> Run:
    """On-demand UI form submit → a single-record run."""
    records = [_coerce_types(template, dict(form_data))]
    return create_run(template, records, TriggerType.ON_DEMAND,
                      output_format=output_format, binding=binding)


def run_from_json(template: Template, raw, *,
                  output_format: str | None = None, binding: Binding | None = None,
                  trigger: str = TriggerType.ON_DEMAND) -> Run:
    """On-demand API / pasted JSON → object (single) or array (batch)."""
    records = _normalize_json(raw)
    records = [_coerce_types(template, r) for r in records]
    return create_run(template, records, trigger,
                      output_format=output_format, binding=binding)


def run_from_csv(template: Template, file_obj, *,
                 output_format: str | None = None, binding: Binding | None = None) -> Run:
    """Uploaded CSV → one record per row (header row = field names)."""
    records = _normalize_csv(file_obj)
    records = [_coerce_types(template, r) for r in records]
    return create_run(template, records, TriggerType.ON_DEMAND,
                      output_format=output_format, binding=binding)


def run_from_webhook(binding: Binding, raw) -> Run:
    """Inbound webhook POST → object or array, using the binding's defaults."""
    records = _normalize_json(raw)
    records = [_coerce_types(binding.template, r) for r in records]
    return create_run(binding.template, records, TriggerType.WEBHOOK, binding=binding)


def run_from_pull(binding: Binding) -> Run:
    """Scheduled pull → fetch a remote source, map fields, then run.

    Enqueued by django-q2's Schedule for a `pull` binding. Network fetch happens
    here (not in the generation worker) so a pull failure is its own clean error.
    """
    if binding.kind != BindingKind.PULL:
        raise DataSourceError(f"binding {binding.id} is not a pull binding")
    raw = _fetch_pull(binding)
    records = _normalize_json(raw)
    records = [_apply_field_map(binding, r) for r in records]
    records = [_coerce_types(binding.template, r) for r in records]
    return create_run(binding.template, records, TriggerType.SCHEDULED, binding=binding)


# ──────────────────────────────────────────────
# The single convergence point
# ──────────────────────────────────────────────
def create_run(template: Template, records: list[dict], trigger: str, *,
               output_format: str | None = None, binding: Binding | None = None) -> Run:
    """Create a QUEUED Run from normalized records and enqueue the worker.

    This is the ONLY way a Run is created. Resolves the output format from the
    explicit arg → binding default → PDF, and validates the batch size.
    """
    if not isinstance(records, list) or not records:
        raise DataSourceError("no records to generate")
    if len(records) > MAX_RECORDS:
        raise DataSourceError(f"batch too large: {len(records)} > {MAX_RECORDS} max")
    if not all(isinstance(r, dict) for r in records):
        raise DataSourceError("every record must be a JSON object / dict")

    fmt = (
        output_format
        or (binding.output_format if binding else None)
        or OutputFormat.PDF
    )
    if fmt not in OutputFormat.values:
        raise DataSourceError(f"unsupported output format: {fmt}")

    # Create the Run and enqueue atomically: if enqueue fails, the Run rolls back
    # so we never leave an orphaned QUEUED row with no task behind it.
    with transaction.atomic():
        run = Run.objects.create(
            template=template,
            binding=binding,
            trigger=trigger,
            status=RunStatus.QUEUED,
            output_format=fmt,
            input_records=records,
            record_count=len(records),
        )
        transaction.on_commit(
            lambda: async_task("docrunner.tasks.run_generation", str(run.id))
        )
    return run


# ──────────────────────────────────────────────
# Normalization
# ──────────────────────────────────────────────
def _normalize_json(raw) -> list[dict]:
    """Accept a JSON string, a dict, or a list; return a list of dicts."""
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            raise DataSourceError(f"invalid JSON: {exc}") from exc

    if isinstance(raw, dict):
        # A wrapper like {"records": [...]} is unwrapped; a plain object is one record.
        if set(raw.keys()) == {"records"} and isinstance(raw["records"], list):
            return list(raw["records"])
        return [raw]
    if isinstance(raw, list):
        return raw
    raise DataSourceError("JSON must be an object or an array of objects")


def _normalize_csv(file_obj) -> list[dict]:
    """Read a CSV (with header row) into a list of row dicts."""
    data = file_obj.read()
    if isinstance(data, bytes):
        data = data.decode("utf-8-sig")  # tolerate a BOM from Excel exports
    reader = csv.DictReader(io.StringIO(data))
    if not reader.fieldnames:
        raise DataSourceError("CSV has no header row")
    rows = [dict(row) for row in reader]
    if not rows:
        raise DataSourceError("CSV has a header but no data rows")
    return rows


def _coerce_types(template: Template, record: dict) -> dict:
    """Best-effort coercion of string inputs (from forms/CSV) toward the schema's
    declared field types. Values that don't parse are left as-is so the template
    still renders something rather than erroring."""
    type_by_name = {
        f["name"]: f.get("type", "string")
        for f in template.schema.get("fields", [])
    }
    out = {}
    for key, val in record.items():
        ftype = type_by_name.get(key, "string")
        out[key] = _coerce_one(val, ftype)
    return out


def _coerce_one(val, ftype: str):
    if not isinstance(val, str):
        return val  # already typed (came from JSON)
    s = val.strip()
    if ftype == "number":
        try:
            return int(s) if s.lstrip("-").isdigit() else float(s)
        except ValueError:
            return val
    if ftype == "boolean":
        low = s.lower()
        if low in ("true", "yes", "1"):
            return True
        if low in ("false", "no", "0"):
            return False
        return val
    if ftype == "list":
        # CSV/form lists arrive as JSON text or a comma-separated string.
        if s.startswith("["):
            try:
                return json.loads(s)
            except ValueError:
                pass
        return [p.strip() for p in s.split(",")] if s else []
    return val  # string / date / unknown → leave untouched


# ──────────────────────────────────────────────
# Scheduled pull
# ──────────────────────────────────────────────
def _fetch_pull(binding: Binding):
    """Fetch the configured remote source for a pull binding. Returns parsed JSON."""
    cfg = binding.config or {}
    url = cfg.get("url")
    if not url:
        raise DataSourceError("pull binding has no 'url' in config")
    method = (cfg.get("method") or "GET").upper()

    headers = dict(cfg.get("headers") or {})
    secret_name = cfg.get("secret_name")
    if secret_name:
        # Convention: inject the secret as a Bearer token unless a header is given.
        token = _secret(secret_name)
        headers.setdefault("Authorization", f"Bearer {token}")

    try:
        resp = requests.request(method, url, headers=headers,
                                json=cfg.get("body"), timeout=PULL_TIMEOUT)
    except requests.RequestException as exc:
        raise DataSourceError(f"pull fetch failed: {exc}") from exc
    if resp.status_code >= 400:
        raise DataSourceError(f"pull source returned HTTP {resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise DataSourceError(f"pull source did not return JSON: {exc}") from exc


def _apply_field_map(binding: Binding, record: dict) -> dict:
    """Remap a pulled record's keys to template placeholders via config.field_map.

    field_map shape: {"placeholder_name": "json.path.into.record"}
    Supports simple dotted paths (a.b.c) and bracket indices (items[0].name).
    If no field_map is set, the record passes through unchanged.
    """
    field_map = (binding.config or {}).get("field_map")
    if not field_map:
        return record
    mapped = {}
    for placeholder, path in field_map.items():
        mapped[placeholder] = _extract_path(record, path)
    return mapped


def _extract_path(obj, path: str):
    """Resolve a dotted/bracketed path against a nested dict/list. None if absent."""
    cur = obj
    for token in _path_tokens(path):
        if isinstance(token, int):
            if isinstance(cur, list) and -len(cur) <= token < len(cur):
                cur = cur[token]
            else:
                return None
        else:
            if isinstance(cur, dict) and token in cur:
                cur = cur[token]
            else:
                return None
    return cur


def _path_tokens(path: str):
    """Split 'items[0].name' → ['items', 0, 'name']."""
    for part in path.lstrip("$.").split("."):
        if not part:
            continue
        name, _, rest = part.partition("[")
        if name:
            yield name
        while rest:
            idx, _, rest = rest.partition("]")
            if idx:
                yield int(idx)
            rest = rest.lstrip("[")


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
class DataSourceError(Exception):
    """Input could not be normalized into records, or a pull failed."""


def _secret(name: str) -> str:
    try:
        return Secret.objects.get(name=name).value
    except Secret.DoesNotExist:
        raise DataSourceError(f"secret '{name}' not found") from None
