/* Copyright 2026 OpenSynergy Indonesia
 * Copyright 2026 PT. Simetri Sinergi Indonesia
 * License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl). */

/**
 * Bootstraps the vendored Swagger UI (static/src/lib/swagger-ui) against
 * this module's own OpenAPI document endpoint.
 *
 * `validatorUrl: null` is binding, not cosmetic (backlog issue #16's
 * Keputusan Desain): without it, swagger-ui silently sends every loaded
 * document to https://validator.swagger.io on its own, which would be an
 * external request this module is not allowed to make.
 */
/* global SwaggerUIBundle, SwaggerUIStandalonePreset */
(function () {
    "use strict";

    function boot() {
        var root = document.getElementById("swagger-ui");
        if (!root) {
            return;
        }
        window.ui = SwaggerUIBundle({
            url: root.getAttribute("data-openapi-url"),
            dom_id: "#swagger-ui",
            presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
            layout: "StandaloneLayout",
            validatorUrl: null,
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", boot);
    } else {
        boot();
    }
})();
