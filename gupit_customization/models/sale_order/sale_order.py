from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    salesman_id = fields.Many2one(
        'hr.employee',
        string='Salesman',
        tracking=True,
    )
    regular_commission = fields.Monetary(
        string='Regular Commission',
        currency_field='currency_id',
        tracking=True,
    )
    over_the_counter_commission = fields.Monetary(
        string='Over-The-Counter Commission',
        currency_field='currency_id',
        tracking=True,
    )
