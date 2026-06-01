# DocRunner

A self-hosted document-automation platform. Upload a `.docx` or `.xlsx` template
with `{{placeholders}}`, feed it data, and generate finished documents — DOCX,
XLSX, or PDF — on demand, on a schedule, or via webhook. Every run is tracked
with a full validation report and downloadable output.

DocRunner is to **documents** what [PyRunner](https://github.com/hassancs91/PyRunner)
is to **scripts**: upload, trigger, monitor, nothing else to configure. It borrows
PyRunner's single-container, single-owner, SQLite-backed model and adds a document
generation engine (docxtpl + openpyxl + LibreOffice).

## Features

- **Templates** — upload `.docx`/`.xlsx`; placeholders are extracted automatically into a schema.
- **Three triggers** — on-demand (UI form, pasted JSON, or CSV upload), scheduled pull, and inbound webhook.
- **Single + batch** — one record or a list; batches produce one file per record plus a zip.
- **Three output formats** — DOCX and XLSX direct, PDF via LibreOffice.
- **All-async** — every generation runs on a background worker; the UI polls for completion.
- **Delivery** — email the finished file or POST it to a webhook callback, with retries.
- **Run history** — status, timing, validation report, and a log for every run.
- **Encrypted secrets** — SMTP and pull credentials stored Fernet-encrypted at rest.
- **Single container** — web server + worker + LibreOffice in one Docker image.

## Architecture

```
trigger ─► datasources.py ─► Run (QUEUED) ─► [django-q2 worker]
(form/JSON/                  normalizes        │
 CSV/webhook/                input to a         ├─ tasks.py: validate → fill → convert → store
 schedule)                   list of records   │   (docxtpl / openpyxl / LibreOffice)
                                                └─ deliveries.py: email / webhook (with retry)
```

| Module | Responsibility |
|---|---|
| `models.py` | Six models: Template, Binding, Run, Output, Delivery, Secret |
| `datasources.py` | Normalize any input into records; create the Run; enqueue the worker |
| `services/extract.py` | Pull the placeholder schema out of an uploaded template |
| `tasks.py` | The generation worker: validate, fill, convert, persist, hand off delivery |
| `deliveries.py` | Send outputs by email/webhook with exponential-backoff retry |
| `views.py` | Owner UI, JSON API, and the public webhook endpoint |

## Tech stack

Django · django-q2 (worker + scheduler) · SQLite · LibreOffice (PDF) · Tailwind-style
hand-rolled CSS · gunicorn · Docker. Mirrors PyRunner except for the bundled
LibreOffice, which is what makes PDF output possible.

## Quick start (Docker)

```bash
git clone <your-repo> docrunner && cd docrunner
cp .env.example .env
# Fill in SECRET_KEY and ENCRYPTION_KEY — see commands in .env.example
docker compose up -d
```

Then create the owner account:

```bash
docker compose exec web python manage.py createsuperuser
```

Open `http://localhost:8000` and sign in.

> **Back up `ENCRYPTION_KEY`.** Losing it makes every stored Secret unrecoverable.

## Configuration

All via environment (see `.env.example`). The two required keys:

| Variable | How to generate |
|---|---|
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |

Everything else (hosts, workers, SMTP, timezone) has sensible defaults documented
in `.env.example`.

## Using it

### 1. Upload a template

Author a Word or Excel file with placeholders:

- Values: `{{ client }}`, `{{ amount }}`
- Repeating rows (DOCX): `{% for item in items %}{{ item.name }}{% endfor %}`
- Conditionals (DOCX): `{% if paid %}PAID{% endif %}`

Upload it; DocRunner extracts the schema and shows the detected fields.

### 2. Generate

On the template page, either fill the auto-generated form, paste JSON (an object
for one document, an array for a batch), or upload a CSV (one row per document).
Pick an output format and generate. You land on the run page, which refreshes
until the document is ready to download.

### 3. Automate (optional)

**API** — generate programmatically:

```bash
curl -X POST http://localhost:8000/api/templates/<template-id>/generate \
  -H "Content-Type: application/json" \
  -d '{"records": [{"client": "Acme", "amount": 4200}], "output_format": "pdf"}'
# → {"run_id": "...", "status": "queued"}

curl http://localhost:8000/api/runs/<run-id>            # status + report
curl -OJ http://localhost:8000/api/runs/<run-id>/output # download
```

**Webhook** — create a webhook Binding (Django admin for now), copy its token,
and POST data to `/hooks/<token>`. Sign the body with the binding's secret in an
`X-DocRunner-Signature: sha256=<hmac>` header.

**Scheduled pull** — create a `pull` Binding with a `url`, optional `secret_name`
(injected as a Bearer token), a `field_map`, and a schedule. django-q2 fires it.

### 4. Manage secrets & bindings

Use the Django admin at `/admin/`:

- **Secrets** — add `SMTP_PASSWORD` and any pull API tokens. Values are write-only:
  you set a new plaintext, but the stored value is never shown back.
- **Bindings** — create webhook/pull/form/upload bindings, set default output
  format, delivery, and the per-record `missing_policy` (error vs. blank).

## Project layout

```
docrunner/
  models.py            datasources.py    tasks.py
  deliveries.py        views.py          urls.py
  admin.py             apps.py
  services/extract.py
  templates/docrunner/ ...               # UI pages
  templates/registration/login.html
docrunner_project/
  settings.py          urls.py           wsgi.py
manage.py  Dockerfile  entrypoint.sh  requirements.txt  .env.example
```

## Design decisions (locked)

- **Single-owner.** No multi-tenancy; the login is a gate. Self-authored templates
  are trusted, so Jinja sandboxing is defense-in-depth rather than a hostile-input
  defense.
- **Local volume only.** SQLite, templates, and outputs all live on `/app/data`.
  Object storage is a post-v1 option.
- **All-async.** No synchronous generation path; the worker owns every run.
- **PDF cold-start accepted.** No warm LibreOffice process — each conversion is
  self-contained, matching PyRunner's per-run isolation.

## Limitations / roadmap

- The auto-generated form covers flat fields; use **Paste JSON** for templates
  with `{% for %}` loops. A repeating-row form builder is planned.
- Bindings are managed via the admin/API; a dedicated binding UI is planned.
- Object-storage output, multi-tenancy, template versioning, and e-signature are
  future work.

## License

Choose one (MIT recommended to match PyRunner).
