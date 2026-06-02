# DocRunner — v2 Specification

*Builds on the shipped v1 (single-owner, local-volume, all-async, Django + django-q2 + LibreOffice on Coolify). This document defines what v2 adds and why.*

**Status:** draft for review · **Predecessor:** v1 (deployed at docrunner.owncpanel.online)

---

## 1. Where v1 landed

v1 shipped and works: upload a `.docx`/`.xlsx` template → schema auto-extracted → generate via form / JSON / CSV / API / webhook → DOCX/XLSX/PDF output → run history → email & webhook delivery → encrypted secrets → admin. Deployed as a single container on Coolify.

**Carried-over v1 roadmap items** (planned but not yet built — fold into v2):
- Dedicated binding-management UI (bindings are admin/API-only today).
- Richer form builder for `{% for %}` loop data (flat-fields + paste-JSON only today).
- Object-storage output (local volume only today).

v2 takes these plus the new themes below.

---

## 2. v2 themes

v2 has five themes, roughly in priority order:

1. **Authoring** — stop requiring users to hand-build templates.
2. **Usability** — make bindings, loops, and delivery first-class in the UI.
3. **Scale & durability** — handle real volume and large payloads.
4. **Integrations** — fit into other systems (storage, signing, more delivery).
5. **Multi-user** — optional move beyond single-owner.

---

## 3. Theme 1 — Authoring

The biggest friction in v1: the user must already have a template with correct `{{placeholder}}` syntax. v2 lowers that barrier.

- **In-browser template editor.** A simple editor to create/edit a template's text and insert placeholders from a palette, without round-tripping through Word. Start with a rich-text → DOCX export; full fidelity can come later.
- **Placeholder-from-upload assist.** When a plain document is uploaded with no placeholders, detect likely variable spots (dates, names, amounts, blanks) and suggest turning them into `{{fields}}`.
- **Template versioning.** Each save creates a version; runs record which version produced them; roll back to a prior version. (Schema lives per-version.)
- **Template preview.** Render a template with sample/dummy data so the user sees the layout before running a real batch.

---

## 4. Theme 2 — Usability

Make the things that are admin/API-only in v1 into proper product surfaces.

- **Binding management UI.** Create/edit/disable form, upload, webhook, and pull bindings from the app — not the Django admin. Show the webhook URL + signing secret with a copy button and a "test" button that fires a sample payload.
- **Loop/repeating-row form builder.** A real UI for `{% for %}` data: add/remove rows for list sections (line items, attendees), so users aren't forced into paste-JSON for anything with a loop. This was explicitly deferred from v1.
- **Delivery management UI.** Configure email/webhook delivery per binding visually; view delivery status and manually retry failed deliveries (the model already supports retry; expose it).
- **Run UX.** Live progress without full-page refresh (replace the 3-second meta-refresh with polling or SSE); re-run a past run with the same inputs; bulk-download outputs.
- **Field types & validation.** Let the user correct the auto-inferred field types and mark fields required/optional, with validation in the form before a run is created.

---

## 5. Theme 3 — Scale & durability

v1 stores everything inline and on a single SQLite file. v2 hardens this for real use.

- **Large input offloading.** `Run.input_records` is stored inline JSON today; offload large batch payloads to a file reference so big CSVs don't bloat the DB.
- **Output retention / cleanup.** A scheduled task to expire old outputs (configurable retention) so the data volume doesn't grow unbounded.
- **Postgres option.** Allow swapping SQLite for Postgres for higher concurrency (keep SQLite as the zero-config default). django-q2 already supports an ORM broker on either.
- **Batch throughput.** Parallelize record generation within a batch across workers; the PDF cold-start cost matters more at scale, so revisit a warm-LibreOffice pool here (explicitly deferred in v1).
- **Concurrency safety.** Confirm the per-call LibreOffice profile-dir approach holds under many simultaneous workers; add a queue/limit if needed.

---

## 6. Theme 4 — Integrations

- **Object storage output (S3/R2).** Deferred from v1. Write outputs to S3-compatible storage; deliver a presigned URL instead of (or alongside) the file. Swap the storage backend, not the schema.
- **More delivery channels.** Slack/Teams message with the file, FTP/SFTP drop, or write back to a Google Drive / Dropbox folder.
- **E-signature handoff.** After generating a contract, hand the PDF to a signing provider (DocuSign/Dropbox Sign) and track signature status on the run.
- **Inbound data connectors for pulls.** Beyond a generic URL pull: typed connectors (Google Sheets, Airtable, a database query) with a guided field-map UI instead of hand-written JSONPath.

---

## 7. Theme 5 — Multi-user (optional)

v1 is deliberately single-owner. If DocRunner is shared with a team or offered to others, v2 can add:

- **Users & roles.** Owner/editor/viewer; per-user template libraries. This is the migration that adds `owner` FKs to Template/Binding/Secret (called out in the v1 data model as the future path).
- **Per-tenant isolation.** With untrusted template authors, the Jinja sandbox stops being mere hygiene and becomes load-bearing — tighten SSTI defenses and macro stripping accordingly.
- **Audit log.** Who generated/changed what, when.
- **API keys & rate limits.** Scoped tokens per user/integration instead of relying on the single owner session.

This theme is gated on an actual need to share the instance; skip it if DocRunner stays personal.

---

## 8. Suggested v2 milestones

- **v1.1 (quick wins):** binding-management UI + delivery UI + manual delivery retry + run re-run. (Surfaces existing model capabilities; low risk.)
- **v1.2 (authoring):** template versioning + preview-with-dummy-data + field-type editing.
- **v1.3 (loops & scale):** repeating-row form builder + large-input offloading + output retention task.
- **v2.0 (integrations):** object storage + presigned-URL delivery + one e-signature or Slack/SFTP channel.
- **v2.x (optional):** multi-user, Postgres, typed pull connectors, parallel batch + warm-LibreOffice pool.

---

## 9. Open questions to settle before building

1. Is DocRunner staying **single-owner** or moving multi-user? (Gates Theme 5 and the whole security posture.)
2. Is the in-browser **authoring editor** worth the complexity, or is "upload from Word" good enough and effort better spent on bindings/loops?
3. Expected **volume** — dozens of docs/day or thousands? (Decides whether Postgres + parallel batch is v2 or much later.)
4. Which **one integration** matters most first — object storage, e-signature, or a delivery channel?
