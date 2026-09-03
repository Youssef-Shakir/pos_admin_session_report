# -*- coding: utf-8 -*-
from odoo import models, fields


class PosConfig(models.Model):
    _inherit = 'pos.config'

    session_report_template = fields.Selection([
        ('ask', 'Ask Every Time'),
        ('standard', 'Standard Report'),
        ('custom', 'Custom Report (English)'),
        ('custom_arabic', 'Custom Report (Arabic)'),
    ], string='Session Report Template', default='ask',
       help='Select the default report template to print when closing session or clicking Print Report')
