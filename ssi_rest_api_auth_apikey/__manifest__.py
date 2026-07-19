# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
{
    "name": "SSI REST API - API Key Authentication",
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
        "ssi_rest_api",
    ],
    "data": [
        "security/res_groups/ssi_rest_api_key.xml",
        "security/ir_model_access/ssi_rest_api_key.xml",
        "security/ir_rule/ssi_rest_api_key.xml",
        "views/ssi_rest_api_key_views.xml",
        "data/ssi_rest_auth_scheme_data.xml",
    ],
}
