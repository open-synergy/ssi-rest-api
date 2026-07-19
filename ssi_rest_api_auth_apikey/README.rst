.. image:: https://img.shields.io/badge/licence-AGPL--3-blue.svg
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3

=====================================
SSI REST API - API Key Authentication
=====================================

Adds a scoped, profile-bound REST API key authentication scheme
(``ssi_rest_api_key``) on top of ``ssi_rest_api``. Unlike the built-in
``bearer`` scheme -- a thin wrapper around Odoo core's own
``res.users.apikeys``, where every key of a given user shares the same
scope -- each key created here carries its own ``ssi_rest_access_profile``,
so a single user can hold several keys with independent, narrower access
scopes.

Keys are stored hashed (``passlib`` ``pbkdf2_sha512``); the raw key value
is only ever shown once, at generation time, and is never persisted.
Lookup at authentication time uses an indexed prefix (``key_index``)
followed by hash verification, never a full-table scan.

A user only sees and manages their own keys; an administrator (the
"REST API Key - Administrator" group) sees every key.


Installation
============

To install this module, you need to:

1.  Clone the branch 19.0 of the repository https://github.com/open-synergy/ssi-rest-api
2.  Add the path to this repository in your configuration (addons-path)
3.  Update the module list (Must be on developer mode)
4.  Go to menu *Apps -> Apps -> Main Apps*
5.  Search For *SSI REST API - API Key Authentication*
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
