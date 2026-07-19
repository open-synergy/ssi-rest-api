.. image:: https://img.shields.io/badge/licence-AGPL--3-blue.svg
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3

====================================
SSI REST API - OAuth2 Authentication
====================================

Turns Odoo into an OAuth2 authorization server for third-party client
applications: registered clients (``ssi_rest_oauth_client``, with an
allow-listed set of exact ``redirect_uri`` values) can obtain, refresh,
and have revoked access tokens (``ssi_rest_oauth_token``) through the
``authorization_code`` grant (with mandatory PKCE, RFC 7636),
``client_credentials``, and ``refresh_token`` -- never the deprecated
OAuth 1.0a protocol, the Resource Owner Password Credentials or implicit
grants, nor OpenID Connect.

Every client secret and issued token is stored hashed (``passlib``
``pbkdf2_sha512``), the same technique ``ssi_rest_api_auth_apikey`` and
Odoo core's own ``res.users.apikeys`` already use; the raw value is only
ever shown once, at issuance time, and is never persisted. Expired
codes/tokens are purged automatically through Odoo's own
``ir.autovacuum`` mechanism, never a bespoke scheduled action.

Endpoints added under ``/api/v1/oauth2/``: ``authorize`` (browser,
requires an existing Odoo session), ``token`` (grant exchange), and
``revoke``. Access tokens issued here are subsequently accepted as a
``Bearer`` credential on every other ``ssi_rest`` endpoint through a
dedicated authentication provider (``ssi_rest_auth_oauth2``).


Installation
============

To install this module, you need to:

1.  Clone the branch 19.0 of the repository https://github.com/open-synergy/ssi-rest-api
2.  Add the path to this repository in your configuration (addons-path)
3.  Update the module list (Must be on developer mode)
4.  Go to menu *Apps -> Apps -> Main Apps*
5.  Search For *SSI REST API - OAuth2 Authentication*
6.  Install the module


Bug Tracker
===========

Bugs are tracked on `GitHub Issues
<https://github.com/open-synergy/ssi-rest-api/issues>`_. In case of trouble, please
check there if your issue has already been reported. If you spotted it first,
help us smash it by providing detailed and welcomed feedback.


Credits
=======

Contributors
------------

* Andhitia Rama <andhitia.r@gmail.com>

Maintainer
----------

.. image:: https://simetri-sinergi.id/logo.png
   :alt: PT. Simetri Sinergi Indonesia
   :target: https://simetri-sinergi.id

This module is maintained by the PT. Simetri Sinergi Indonesia.
