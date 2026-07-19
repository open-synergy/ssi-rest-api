.. image:: https://img.shields.io/badge/licence-AGPL--3-blue.svg
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3

=================================
SSI REST API - JWT Authentication
=================================

Adds a REST authentication scheme (``jwt``) that accepts JWT bearer tokens
issued by an external identity provider (Authentik, Keycloak, Entra, ...)
configured as a ``ssi_rest_jwt_issuer`` record.

Every token is fully verified: signature (against the issuer's
``shared_secret`` for HMAC algorithms, or its ``jwks_url`` for asymmetric
ones -- fetched through a TTL-bound cache, never on every request), the
``iss`` and ``aud`` claims, and ``exp``/``nbf`` with the issuer's configured
clock-skew leeway. The signing algorithm accepted is always the one
configured on the issuer record, explicitly, never inferred from the
token's own header.

A verified token's identity claim (``user_claim``) is matched against an
existing ``res.users`` record (by ``login`` or ``email``, per
``user_match_field``); a token whose claim does not match any user is
rejected. This module never creates a user from a token -- there is no
just-in-time provisioning.

This module only verifies tokens issued elsewhere; it does not issue
tokens itself.


Installation
============

To install this module, you need to:

1.  Clone the branch 19.0 of the repository https://github.com/open-synergy/ssi-rest-api
2.  Add the path to this repository in your configuration (addons-path)
3.  Update the module list (Must be on developer mode)
4.  Go to menu *Apps -> Apps -> Main Apps*
5.  Search For *SSI REST API - JWT Authentication*
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
