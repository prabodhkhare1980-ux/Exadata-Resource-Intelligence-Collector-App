"""Dash pages package.

Each module registers itself with Dash's page registry via
``dash.register_page``. Routes match the navigation defined in
``components/layout.py``.

Future deep-link routes are planned:
- /cluster/<cluster>
- /db/<db_unique_name>
- /host/<host>

They are not implemented yet, but the page modules and layout are designed
so they can be added without restructuring the app.
"""
