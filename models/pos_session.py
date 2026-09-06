# -*- coding: utf-8 -*-
from odoo import models, api, fields


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _report_localize(self, value):
        """Return a datetime formatted in the current user's timezone.

        ``start_at`` and friends are stored naive in UTC. Formatting them
        directly prints UTC, which does not match the clock on the POS
        machine. ``context_timestamp`` shifts them to the user's timezone
        (the same convention the standard Odoo receipts use).
        """
        if not value:
            return ''
        return fields.Datetime.context_timestamp(self, value).strftime('%Y-%m-%d %H:%M')

    @api.model
    def get_custom_session_report_data(self, session_id):
        """Get all data needed for the custom session report."""
        session = self.browse(session_id)
        if not session.exists():
            return {}

        # Get all completed orders (including refunds which have negative amounts)
        all_orders = self.env['pos.order'].search([
            ('session_id', '=', session_id),
            ('state', 'in', ['paid', 'done', 'invoiced'])
        ])

        # Separate positive orders (sales) and negative orders (refunds)
        sale_orders = all_orders.filtered(lambda o: o.amount_total >= 0)
        refund_orders = all_orders.filtered(lambda o: o.amount_total < 0)

        # Sales by category (using price_subtotal_incl which includes tax)
        category_sales = {}
        for order in sale_orders:
            for line in order.lines:
                categ = line.product_id.pos_categ_ids[:1]
                categ_name = categ.name if categ else 'Uncategorized'
                if categ_name not in category_sales:
                    category_sales[categ_name] = {'qty': 0, 'total': 0}
                category_sales[categ_name]['qty'] += line.qty
                category_sales[categ_name]['total'] += line.price_subtotal_incl

        category_list = [
            {'name': name, 'qty': data['qty'], 'total': data['total']}
            for name, data in category_sales.items()
        ]

        # Sales by employee (who ORIGINALLY created/took the order)
        # Use x_original_employee_id first, fall back to employee_id, then user_id
        employee_sales = {}

        for order in sale_orders:
            # Priority: x_original_employee_id > employee_id > user_id
            if order.x_original_employee_id:
                emp_name = order.x_original_employee_id.name
            elif order.employee_id:
                emp_name = order.employee_id.name
            elif order.user_id:
                emp_name = order.user_id.name
            else:
                emp_name = 'Unknown'

            if emp_name not in employee_sales:
                employee_sales[emp_name] = {'orders': 0, 'total': 0}
            employee_sales[emp_name]['orders'] += 1
            employee_sales[emp_name]['total'] += order.amount_total

        employee_list = [
            {'name': name, 'orders': data['orders'], 'total': data['total']}
            for name, data in employee_sales.items()
        ]

        # Calculate Gross Total (before discount) - includes tax
        # For lines with discount: original_price = price_subtotal_incl / (1 - discount/100)
        # For lines without discount: original_price = price_subtotal_incl
        gross_total = 0
        total_discount = 0

        for order in sale_orders:
            for line in order.lines:
                if line.discount and line.discount > 0:
                    # Calculate original price before discount
                    original_price = line.price_subtotal_incl / (1 - line.discount / 100)
                    gross_total += original_price
                    total_discount += original_price - line.price_subtotal_incl
                else:
                    gross_total += line.price_subtotal_incl

        # Also account for discounts on refunds (reduces the discount amount)
        for order in refund_orders:
            for line in order.lines:
                if line.discount and line.discount > 0:
                    # For refunds, price_subtotal_incl is negative
                    # Original would be: price_subtotal_incl / (1 - discount/100)
                    original_price = line.price_subtotal_incl / (1 - line.discount / 100)
                    # Discount on refund reduces total discount
                    total_discount += original_price - line.price_subtotal_incl

        # Total refunds (absolute value of negative orders)
        total_refunds = abs(sum(order.amount_total for order in refund_orders))

        # Net total = what was actually collected (sum of all order amounts)
        # This should equal: gross_total - total_discount - total_refunds
        net_total = sum(order.amount_total for order in all_orders)

        # Number of deleted/cancelled orders
        deleted_orders = self.env['pos.order'].search_count([
            ('session_id', '=', session_id),
            ('state', '=', 'cancel')
        ])

        # Payment methods
        payments = {}
        for order in all_orders:
            for payment in order.payment_ids:
                method_name = payment.payment_method_id.name
                if method_name not in payments:
                    payments[method_name] = 0
                payments[method_name] += payment.amount

        payment_list = [
            {'method': name, 'total': total}
            for name, total in payments.items()
        ]

        # Closing cashier
        closing_cashier = session.user_id.name or 'Unknown'

        # Number of transactions
        num_transactions = len(all_orders)

        return {
            'session_name': session.name,
            'config_name': session.config_id.name,
            'opening_date': self._report_localize(session.start_at),
            'closing_date': self._report_localize(session.stop_at),
            # Server "now", localized to the user's timezone so it matches the
            # clock on the POS machine.
            'print_date': self._report_localize(fields.Datetime.now()),
            'closing_cashier': closing_cashier,
            'categories': category_list,
            'employees': employee_list,
            'gross_total': gross_total,
            'total_discount': total_discount,
            'total_refunds': total_refunds,
            'net_total': net_total,
            'deleted_orders': deleted_orders,
            'num_transactions': num_transactions,
            'payments': payment_list,
            'company_name': 'donialink.com',
            'author': 'Yousif Shakir',
        }
