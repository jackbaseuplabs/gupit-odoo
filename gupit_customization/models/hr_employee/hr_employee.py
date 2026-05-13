from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    sale_order_ids = fields.One2many(
        'sale.order',
        'salesman_id',
        string='Sales Orders',
    )
