# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
{
    "name": "SSI REST API",
    "version": "19.0.1.3.0",
    "website": "https://simetri-sinergi.id",
    "author": "OpenSynergy Indonesia, PT. Simetri Sinergi Indonesia",
    "contributors": [
        "Andhitia Rama <andhitia.r@gmail.com>",
    ],
    "license": "AGPL-3",
    "installable": True,
    "application": False,
    "depends": [
        "base",
        "web",
        "ssi_master_data_mixin",
    ],
    "data": [
        "data/ir_config_parameter_data.xml",
        "security/ir_module_category/ssi_rest_api.xml",
        "security/res_groups/ssi_rest_auth_scheme.xml",
        "security/ir_model_access/ssi_rest_auth_scheme.xml",
        "menu.xml",
        "views/ssi_rest_auth_scheme_views.xml",
        "data/ssi_rest_auth_scheme_data.xml",
        "security/ir_model_access/ssi_rest_access_profile.xml",
        "views/ssi_rest_access_profile_views.xml",
        "views/res_users_views.xml",
    ],
}
