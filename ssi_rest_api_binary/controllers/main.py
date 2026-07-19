# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Download/upload REST endpoints over an arbitrary binary/image field of
an arbitrary model+record.

Functional requirements were derived from analysing ``muk_rest``'s
behaviour (used **only** as a functional reference — its license is MuK
Proprietary v1.0); this is a clean-room implementation: no code, naming,
or file structure is copied from it. ``muk_rest`` exposes 9 download-route
variants and 11 image-route variants; backlog issue #13's Keputusan
Desain deliberately collapses all of that into exactly two routes (one
``GET`` download, one ``POST`` upload) with variant behaviour carried as
query parameters instead of separate routes.

BINDING (do not remove this comment when editing this file): both routes
below are built on core's own ``ir.binary`` + ``http.Stream`` — resizing,
ETag/If-None-Match, and cache headers are core's, never reimplemented
here. ``sudo()`` is forbidden anywhere in this module — see
``ssi_rest_api/models/ssi_rest_access_profile.py`` for the subtractive-only
rationale this inherits from backlog issue #7.

Binding risk (Keputusan Desain, inherited from issue #11): a non-DB side
effect (filestore write) only ever happens through ``record.write()``
inside ``binary_upload`` below, which is itself the one DB effect
``service_model.retrying`` is allowed to re-run — there is no *additional*
non-DB effect (no outbound HTTP, no email, no sequence) in either endpoint
that a retry could duplicate.
"""

import base64

from odoo import http
from odoo.http import request

from odoo.addons.ssi_rest_api.lib.auth import RestAuthError
from odoo.addons.ssi_rest_api.lib.routing import rest_route

from . import _helpers

#: Explicit per-route cap for the upload endpoint (Keputusan Desain:
#: "route unggah wajib menetapkan max_content_length sendiri" — the
#: ``web.max_file_upload_size`` ICP core already applies is a *default*,
#: not something this route may silently rely on for a clear 413 instead
#: of a confusing generic failure). Read through a module-level constant
#: — rather than inlined in the ``max_content_length=`` kwarg below — so
#: tests can shrink it with ``mock.patch`` instead of uploading a real
#: multi-megabyte payload (P6 escape hatch).
MAX_UPLOAD_CONTENT_LENGTH = 25 * 1024 * 1024


def _upload_max_content_length(controller):
    # Core calls this with a single positional arg — the controller
    # instance (`rule.endpoint.func.__self__`, see `odoo/http.py`'s base
    # `Dispatcher.pre_dispatch`) — unlike the unrelated `readonly=`
    # callable convention (`(controller, rule, args)`) used elsewhere in
    # this module family; do not conflate the two signatures.
    return MAX_UPLOAD_CONTENT_LENGTH


class SsiRestBinaryController(http.Controller):
    @rest_route(
        ["/binary/<string:model>/<int:res_id>"],
        auth="ssi_rest",
        methods=["GET"],
        operation="read",
        readonly=True,
    )
    def binary_download(
        self,
        model,
        res_id,
        field=None,
        filename=None,
        filename_field="name",
        mimetype=None,
        download=None,
        width=None,
        height=None,
        crop=None,
        quality=None,
        placeholder=None,
        **kwargs,
    ):
        if not field:
            raise RestAuthError("validation_error", "field is required.", status=422)
        record = _helpers.resolve_record(request.env, model, res_id)
        # `ir.binary` only checks *field*-level access
        # (`_check_field_access`) for an arbitrary model — the row-level
        # ACL/record-rule check below is this endpoint's own
        # responsibility, same as every other endpoint in this module
        # family (never `sudo()`).
        record.check_access("read")

        binary_model = request.env["ir.binary"]
        image_variant = any(
            value not in (None, "")
            for value in (width, height, crop, quality, placeholder)
        )
        if image_variant:
            stream = binary_model._get_image_stream_from(
                record,
                field_name=field,
                filename=filename,
                filename_field=filename_field,
                mimetype=mimetype,
                placeholder=placeholder or None,
                width=int(width or 0),
                height=int(height or 0),
                crop=_helpers.parse_bool(crop),
                quality=int(quality or 0),
            )
        else:
            stream = binary_model._get_stream_from(
                record,
                field_name=field,
                filename=filename,
                filename_field=filename_field,
                mimetype=mimetype,
            )
        return stream.get_response(as_attachment=_helpers.parse_bool(download))

    @rest_route(
        ["/binary/<string:model>/<int:res_id>"],
        auth="ssi_rest",
        methods=["POST"],
        operation="write",
        readonly=False,
        max_content_length=_upload_max_content_length,
    )
    def binary_upload(self, model, res_id, field=None, **kwargs):
        if not field:
            raise RestAuthError("validation_error", "field is required.", status=422)
        record = _helpers.resolve_record(request.env, model, res_id)
        field_def = record._fields.get(field)
        if field_def is None or field_def.type != "binary":
            raise RestAuthError(
                "validation_error", f"{field!r} is not a binary field.", status=422
            )
        uploaded = request.httprequest.files.get("file")
        if uploaded is None:
            raise RestAuthError("validation_error", "file is required.", status=422)
        content = base64.b64encode(uploaded.read())
        # `write()` performs its own ACL/record-rule check; nothing is
        # persisted if it raises (no partial write to undo).
        record.write({field: content})
        return {"id": record.id, "field": field}
