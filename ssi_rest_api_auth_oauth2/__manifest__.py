# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
{
    "name": "SSI REST API - OAuth2 Authentication",
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
        "ssi_rest_api_auth_apikey",
    ],
    "data": [
        "security/ir_model_access/ssi_rest_oauth_client.xml",
        "security/ir_model_access/ssi_rest_oauth_scope.xml",
        "security/ir_model_access/ssi_rest_oauth_token.xml",
        "security/ir_rule/ssi_rest_oauth_token.xml",
        "views/ssi_rest_oauth_scope_views.xml",
        "views/ssi_rest_oauth_client_views.xml",
        "views/ssi_rest_oauth_token_views.xml",
        "data/ssi_rest_auth_scheme_data.xml",
    ],
}
