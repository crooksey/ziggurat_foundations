.. ziggurat_foundations documentation master file, created by
   sphinx-quickstart on Fri May 25 21:03:39 2012.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

ziggurat_foundations
====================

.. image:: /_static/pyramid_logo_red_on_transparent_background.png
   :width: 64 px
   :alt: Pyramid Logo

.. image:: /_static/flask_small.png
   :alt: Flask Logo

High level mixins for adding authorization, resource ownership and permission management
fast, simple and easy. In summary, Ziggurat Foundations is a set of framework agnostic
set of SQLAalchemy classes, so it can be used with Flask, Pyramid or other popular frameworks.
It is the perfect solution for handling complex login and user
management systems, from e-commerce systems, to private intranets or large CMS systems.
It can easily be extended to support any additional features you may need (explained
further in the documentation)

.. hint::

    Ziggurat Foundations aims to simplify user, permission and resource management,
    allowing you to concentrate on application development, as opposed to developing
    your own user and permission based models/code.

**DOCUMENTATION**: http://readthedocs.org/docs/ziggurat-foundations/en/latest/

**BUG TRACKER**: https://github.com/ergo/ziggurat_foundations

**DOCUMENTATION REPO**: https://github.com/ergo/ziggurat_foundations/tree/master/docs

**CHANGELOG**: https://github.com/ergo/ziggurat_foundations/blob/master/CHANGES.md

Contents:

.. toctree::
   :maxdepth: 2

   overview
   configuration
   usage_examples
   integrations
   api/index



.. note::

    By default ziggurat aims at **postgresql 8.4+** (CTE support) as main RDBMS system,
    but currently *everything* except recursive queries(for **optional** resource tree structures)
    is tested using sqlite, and will run on other popular database systems including **mysql**.
    **For other database systems that don't support CTE's fallbacks will be supplied.**

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
