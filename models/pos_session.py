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
    def _report_line_undiscounted(self, line):
        """Tax-included line total before the line discount.

        Computed from the unit price rather than by dividing the discounted
        total by (1 - discount), which breaks on 100% (free) lines.
        """
        taxes = line.tax_ids_after_fiscal_position
        if taxes:
            return taxes.compute_all(
                line.price_unit, line.order_id.currency_id, line.qty,
                product=line.product_id, partner=line.order_id.partner_id,
            )['total_included']
        return line.price_unit * line.qty

    @api.model
    def _report_order_label(self, order):
        """Short order reference as printed on the POS ticket (e.g. 0013)
        plus the table number when the order belongs to a table."""
        ref = (order.pos_reference or order.name or '').split('-')[-1]
        table = order.table_id.table_number if 'table_id' in order._fields and order.table_id else ''
        return ref, str(table or '')

    @api.model
    def _report_employee_name(self, order):
        employee = order.x_original_employee_id or order.employee_id
        return employee.name if employee else (order.user_id.name or '')

    @api.model
    def _get_report_cancelled_orders(self, session):
        """Cancelled orders of the session with their cancel reason (the
        reason fields come from dev_pos_access_rights when installed)."""
        orders = self.env['pos.order'].search(
            [('session_id', '=', session.id), ('state', '=', 'cancel')], order='date_order')
        has_reason = 'cancel_reason' in self.env['pos.order']._fields
        result = []
        for order in orders:
            ref, table = self._report_order_label(order)
            items = ', '.join(
                f"{line.qty:g}x {line.full_product_name or line.product_id.name}"
                for line in order.lines)
            when = (has_reason and order.cancel_date) or order.write_date
            result.append({
                'id': order.id,
                'ref': ref,
                'table': table,
                'time': fields.Datetime.context_timestamp(self, when).strftime('%H:%M') if when else '',
                'by': (has_reason and order.cancel_by) or self._report_employee_name(order),
                'reason': (has_reason and order.cancel_reason) or '',
                'amount': order.amount_total,
                'items': items,
            })
        return result

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

        # Global discount (pos_discount) is a negative line with this product:
        # report it as a discount, not as a sale.
        discount_product = (
            session.config_id.discount_product_id
            if 'discount_product_id' in session.config_id._fields else self.env['product.product']
        )

        def is_global_discount(line):
            return bool(discount_product) and line.product_id == discount_product

        # Sales by category (using price_subtotal_incl which includes tax)
        category_sales = {}
        for order in sale_orders:
            for line in order.lines:
                if is_global_discount(line):
                    continue
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
        discount_orders = {}  # order id -> discount summary of that order

        def add_order_discount(order, amount, item):
            if order.id not in discount_orders:
                ref, table = self._report_order_label(order)
                discount_orders[order.id] = {
                    'ref': ref, 'table': table,
                    'employee': self._report_employee_name(order),
                    'amount': 0, 'items': [],
                }
            discount_orders[order.id]['amount'] += amount
            discount_orders[order.id]['items'].append(item)

        for order in sale_orders:
            for line in order.lines:
                if is_global_discount(line):
                    amount = -line.price_subtotal_incl
                    total_discount += amount
                    add_order_discount(order, amount, line.full_product_name or line.product_id.name)
                elif line.discount and line.discount > 0:
                    original_price = self._report_line_undiscounted(line)
                    amount = original_price - line.price_subtotal_incl
                    gross_total += original_price
                    total_discount += amount
                    add_order_discount(order, amount, f"{line.qty:g}x {line.full_product_name or line.product_id.name} {line.discount:g}%")
                else:
                    gross_total += line.price_subtotal_incl

        # Also account for discounts on refunds (reduces the discount amount)
        for order in refund_orders:
            for line in order.lines:
                if is_global_discount(line):
                    total_discount -= line.price_subtotal_incl
                elif line.discount and line.discount > 0:
                    # For refunds the amounts are negative, so this reduces
                    # the total discount
                    original_price = self._report_line_undiscounted(line)
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
            'discount_orders': [dict(d, items=', '.join(d['items'])) for d in discount_orders.values()],
            'cancelled_orders': self._get_report_cancelled_orders(session),
            'total_refunds': total_refunds,
            'net_total': net_total,
            'deleted_orders': deleted_orders,
            'num_transactions': num_transactions,
            'payments': payment_list,
            'company_name': 'donialink.com',
            'author': 'Yousif Shakir',
        }
