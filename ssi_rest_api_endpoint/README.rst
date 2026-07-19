.. image:: https://img.shields.io/badge/licence-AGPL--3-blue.svg
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3

=================================
SSI REST API - Custom Endpoint
=================================

Lets an administrator define custom REST endpoints as master data records
(``ssi_rest_endpoint``): a ``path`` + HTTP method mapped to a whitelisted
handler — either a public model method
(``odoo.service.model.get_public_method``) or an ``ir.actions.server`` —
served through a single wildcard route under
``/api/v1/x/<path:subpath>``.

Access is subject to the caller's own ACL/record rules and any
``ssi_rest_access_profile`` listed in the endpoint's ``profile_ids`` —
this module never widens access beyond that, and never executes
arbitrary Python code stored on a field.


Installation
============

To install this module, you need to:

1.  Clone the branch 19.0 of the repository https://github.com/open-synergy/ssi-rest-api
2.  Add the path to this repository in your configuration (addons-path)
3.  Update the module list (Must be on developer mode)
4.  Go to menu *Apps -> Apps -> Main Apps*
5.  Search For *SSI REST API - Custom Endpoint*
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
