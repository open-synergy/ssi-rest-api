# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
{
    "name": "SSI REST API - JWT Authentication",
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
    "external_dependencies": {
        # PyPI distribution names, not import names: Odoo 19's
        # check_python_external_dependency() resolves these through
        # importlib.metadata (installed package metadata) first, falling
        # back to import-name resolution only with a deprecation warning.
        # "jwt" is a *different*, unrelated PyPI package (GehirnInc's
        # jwt) from the one this module actually needs -- "pyjwt" is the
        # correct name (PyPI normalizes case, so this matches the PyJWT
        # project), exactly as OCA's own server-auth/auth_jwt module
        # declares it. cryptography backs pyjwt's RS*/ES* algorithm
        # families (this module's default algorithm is RS256).
        "python": ["pyjwt", "cryptography"],
    },
    "data": [
        "security/ir_model_access/ssi_rest_jwt_issuer.xml",
        "views/ssi_rest_jwt_issuer_views.xml",
        "data/ssi_rest_auth_scheme_data.xml",
    ],
}
