# -*- coding: utf-8 -*-
{
    "name": "POS Session Report for Admins (USB Printers)",
    "version": "18.0.1.5.0",
    "category": "Point of Sale",
    "summary": "Print the session sales report on regular USB printers, visible to session admins only",
    "description": """
POS Session Report for Admins
==============================

The built-in "Print Report" menu item (the session sales details report,
printed from the burger menu in the POS session) is normally only shown
when an ePOS/IoT Box network printer is configured
(`pos.config.iface_print_via_proxy`), because it prints directly through
that proxy connection with no fallback for anything else.

This module:

- Makes "Print Report" available even when the POS only has a regular
  (USB-connected / browser-driven) printer, by falling back to the
  standard web print dialog when no proxy printer is connected -
  exactly like the receipt and bill already do.
- Restricts the "Print Report" menu item to session admins/managers when
  Employee Login (pos_hr) is used, hiding it from regular employees. If
  Employee Login isn't used, it stays visible to everyone (there is no
  employee/admin distinction in that case).
- Automatically prints the session sales details report the moment the
  register is closed, so it no longer depends on someone remembering to
  click "Print Report" beforehand.
- Custom session report templates (English and Arabic) with sales by
  category, employee sales, totals, discounts, refunds, and payments.
- Configurable default report template in POS settings.
- Before printing, the orders waiting on the device are sent; with no or a
  poor connection the report is not printed instead of showing old figures.
- At closing the custom reports print the session cash in / out (expenses)
  and the closing: expected, counted and difference (shortage / overage)
  per payment method, with the closing notes.
    """,
    "depends": ["point_of_sale", "pos_hr"],
    "data": [
        "views/pos_config_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_admin_session_report/static/src/js/**/*",
            "pos_admin_session_report/static/src/xml/**/*",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
    "author": "Yousif Shakir",
    "website": "https://donialink.com",
}
