# -*- coding: utf-8 -*-
from odoo import models, fields, api


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def init(self):
        """Populate x_original_employee_id for existing orders that don't have it set."""
        self.env.cr.execute("""
            UPDATE pos_order
            SET x_original_employee_id = employee_id
            WHERE x_original_employee_id IS NULL
            AND employee_id IS NOT NULL
        """)

    # Store the original employee who first created/took the order
    # This field is set only once and never updated
    # Using x_ prefix for automatic POS frontend sync
    x_original_employee_id = fields.Many2one(
        'hr.employee',
        string='Original Employee',
        help='The employee who originally created/took this order (not updated when payment is processed)',
        readonly=True,
        copy=False
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # If x_original_employee_id is provided from frontend, use it
            # Otherwise fall back to employee_id
            if not vals.get('x_original_employee_id'):
                if vals.get('employee_id'):
                    vals['x_original_employee_id'] = vals['employee_id']
        return super().create(vals_list)

    def write(self, vals):
        # Before writing, check if we need to set x_original_employee_id
        # Only set it if it's not already set and not being set in this write
        if 'employee_id' in vals and vals['employee_id']:
            for order in self:
                if not order.x_original_employee_id and 'x_original_employee_id' not in vals:
                    # This is the first time employee_id is being set
                    # Set x_original_employee_id to capture the first employee
                    super(PosOrder, order).write({
                        'x_original_employee_id': vals['employee_id']
                    })
        return super().write(vals)
