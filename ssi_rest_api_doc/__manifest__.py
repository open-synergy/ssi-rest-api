# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
{
    "name": "SSI REST API - Documentation",
    "version": "19.0.1.0.0",
    "website": "https://simetri-sinergi.id",
    "author": "OpenSynergy Indonesia, PT. Simetri Sinergi Indonesia",
    "contributors": [
        "Andhitia Rama <andhitia.r@gmail.com>",
    ],
    "license": "AGPL-3",
    "installable": True,
    "application": False,
    "depends": [
        "ssi_rest_api_orm",
        "ssi_rest_api_introspection",
    ],
    "data": [
        "security/res_groups/ssi_rest_openapi.xml",
        "views/swagger_ui_templates.xml",
    ],
    "assets": {
        "ssi_rest_api_doc.swagger_ui_assets": [
            "ssi_rest_api_doc/static/src/lib/swagger-ui/swagger-ui.css",
            "ssi_rest_api_doc/static/src/lib/swagger-ui/swagger-ui-bundle.js",
            "ssi_rest_api_doc/static/src/lib/swagger-ui/swagger-ui-standalone-preset.js",
            "ssi_rest_api_doc/static/src/js/swagger_ui_init.js",
        ],
    },
}
