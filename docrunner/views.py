"""
docrunner/views.py

The web + API surface. Thin by design: every view normalizes input and hands
off to datasources.py (which creates the Run and enqueues the worker). Nothing
here generates documents inline.

Auth: all owner-facing views require login (single-owner gate). The inbound
webhook is the one public endpoint — authenticated by token + optional HMAC,
exempt from session CSRF.
"""
import hashlib
import hmac
import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, FileResponse, Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from docrunner import datasources
from docrunner.models import (
    Template, Binding, Run, Output, TemplateFormat, OutputFormat,
)
from docrunner.services.extract import extract_schema


# ──────────────────────────────────────────────
# Templates: list + upload
# ──────────────────────────────────────────────
@login_required
def template_list(request):
    templates = Template.objects.all()
    return render(request, "docrunner/template_list.html", {"templates": templates})


@login_required
@require_http_methods(["GET", "POST"])
def template_upload(request):
    if request.method == "GET":
        return render(request, "docrunner/template_upload.html", {})

    upload = request.FILES.get("file")
    if not upload:
        return HttpResponseBadRequest("no file uploaded")

    fmt = _detect_format(upload.name)
    if not fmt:
        return HttpResponseBadRequest("file must be .docx or .xlsx")

    name = request.POST.get("name") or upload.name.rsplit(".", 1)[0]
    template = Template(name=name, fmt=fmt, file=upload)
    template.save()

    # Extract the placeholder schema now that the file is on disk.
    try:
        template.schema = extract_schema(template.file.path, fmt)
        template.save(update_fields=["schema"])
    except Exception as exc:
        template.delete()
        return HttpResponseBadRequest(f"could not parse template: {exc}")

    return redirect("template_detail", template_id=template.id)


@login_required
def template_detail(request, template_id):
    template = get_object_or_404(Template, id=template_id)
    return render(request, "docrunner/template_detail.html", {
        "template": template,
        "fields": template.schema.get("fields", []),
        "has_loops": template.schema.get("has_loops", False),
        "output_formats": OutputFormat.choices,
    })


# ──────────────────────────────────────────────
# Generation (on-demand: form + JSON + CSV)
# ──────────────────────────────────────────────
@login_required
@require_http_methods(["POST"])
def generate_form(request, template_id):
    """UI form submit → single-record run."""
    template = get_object_or_404(Template, id=template_id)
    output_format = request.POST.get("output_format") or OutputFormat.PDF
    # Collect every placeholder field from the posted form.
    field_names = {f["name"] for f in template.schema.get("fields", [])}
    record = {k: v for k, v in request.POST.items() if k in field_names}

    try:
        run = datasources.run_from_form(template, record, output_format=output_format)
    except datasources.DataSourceError as exc:
        return HttpResponseBadRequest(str(exc))
    return redirect("run_detail", run_id=run.id)


@login_required
@require_http_methods(["POST"])
def generate_json(request, template_id):
    """UI 'paste JSON' or API → object or array."""
    template = get_object_or_404(Template, id=template_id)
    output_format = request.POST.get("output_format") or _json_body(request).get(
        "output_format"
    ) or OutputFormat.PDF
    payload = request.POST.get("json") or request.body

    try:
        run = datasources.run_from_json(template, payload, output_format=output_format)
    except datasources.DataSourceError as exc:
        return HttpResponseBadRequest(str(exc))

    if _wants_json(request):
        return JsonResponse({"run_id": str(run.id), "status": run.status}, status=202)
    return redirect("run_detail", run_id=run.id)


@login_required
@require_http_methods(["POST"])
def generate_csv(request, template_id):
    """Uploaded CSV → batch run."""
    template = get_object_or_404(Template, id=template_id)
    upload = request.FILES.get("file")
    if not upload:
        return HttpResponseBadRequest("no CSV uploaded")
    output_format = request.POST.get("output_format") or OutputFormat.PDF

    try:
        run = datasources.run_from_csv(template, upload, output_format=output_format)
    except datasources.DataSourceError as exc:
        return HttpResponseBadRequest(str(exc))
    return redirect("run_detail", run_id=run.id)


# ──────────────────────────────────────────────
# API: generate (programmatic, returns run id)
# ──────────────────────────────────────────────
@csrf_exempt
@login_required
@require_http_methods(["POST"])
def api_generate(request, template_id):
    """POST /api/templates/{id}/generate — JSON object or array body."""
    template = get_object_or_404(Template, id=template_id)
    body = _json_body(request)
    payload = body.get("records", body)  # accept {"records":[...]} or a bare array/object
    output_format = body.get("output_format", OutputFormat.PDF) \
        if isinstance(body, dict) else OutputFormat.PDF

    try:
        run = datasources.run_from_json(
            template, payload, output_format=output_format
        )
    except datasources.DataSourceError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"run_id": str(run.id), "status": run.status}, status=202)


# ──────────────────────────────────────────────
# Runs: history, detail, output download
# ──────────────────────────────────────────────
@login_required
def run_list(request):
    runs = Run.objects.select_related("template").all()[:200]
    return render(request, "docrunner/run_list.html", {"runs": runs})


@login_required
def run_detail(request, run_id):
    run = get_object_or_404(Run.objects.select_related("template"), id=run_id)
    if _wants_json(request):
        return JsonResponse(_run_json(run))
    return render(request, "docrunner/run_detail.html", {
        "run": run,
        "outputs": run.outputs.all(),
        "report": run.report,
    })


@login_required
def api_run_status(request, run_id):
    """GET /api/runs/{id} — status + validation report."""
    run = get_object_or_404(Run, id=run_id)
    return JsonResponse(_run_json(run))


@login_required
def run_output(request, run_id):
    """GET /api/runs/{id}/output — download a file (or the batch archive)."""
    run = get_object_or_404(Run, id=run_id)
    output_id = request.GET.get("output_id")
    if output_id:
        output = get_object_or_404(Output, id=output_id, run=run)
    else:
        # Default: the archive for batches, else the single output.
        output = run.outputs.filter(is_archive=True).first() or run.outputs.first()
    if not output:
        raise Http404("no output for this run")
    return FileResponse(output.file.open("rb"), as_attachment=True,
                        filename=output.filename)


# ──────────────────────────────────────────────
# Inbound webhook (public, token + HMAC authenticated)
# ──────────────────────────────────────────────
@csrf_exempt
@require_http_methods(["POST"])
def webhook_receive(request, token):
    """POST /hooks/{token} — external system fires a generation."""
    binding = get_object_or_404(
        Binding, webhook_token=token, kind="webhook", enabled=True
    )

    # Verify HMAC signature if the binding has a secret (it always mints one).
    if binding.webhook_secret:
        sig = request.headers.get("X-DocRunner-Signature", "")
        expected = "sha256=" + hmac.new(
            binding.webhook_secret.encode(), request.body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return JsonResponse({"error": "invalid signature"}, status=401)

    try:
        payload = json.loads(request.body or b"{}")
        run = datasources.run_from_webhook(binding, payload)
    except (json.JSONDecodeError, datasources.DataSourceError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"run_id": str(run.id), "status": run.status}, status=202)


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def _detect_format(filename: str):
    low = filename.lower()
    if low.endswith(".docx"):
        return TemplateFormat.DOCX
    if low.endswith(".xlsx"):
        return TemplateFormat.XLSX
    return None


def _json_body(request) -> dict:
    try:
        return json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return {}


def _wants_json(request) -> bool:
    return "application/json" in request.headers.get("Accept", "")


def _run_json(run: Run) -> dict:
    return {
        "run_id": str(run.id),
        "template": run.template.name,
        "status": run.status,
        "trigger": run.trigger,
        "output_format": run.output_format,
        "record_count": run.record_count,
        "report": run.report,
        "outputs": [
            {"id": str(o.id), "filename": o.filename, "size_bytes": o.size_bytes,
             "is_archive": o.is_archive}
            for o in run.outputs.all()
        ],
        "queued_at": run.queued_at.isoformat() if run.queued_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_ms": run.duration_ms,
    }
