{
    "name": "Gupit Customization",
    "version": "19.0.1.0.0",
    "summary": "Post-Dated Check (PDC) lifecycle for Odoo 19",
    "description": (
        "Standalone PDC feature: check-method registration, PDC fields on "
        "payments and the register wizard, deposit/bounced/pulled-out workflow, "
        "batch deposit, and clearing-driven bank statement line creation."
    ),
    "category": "Accounting",
    "author": "Baseup Labs",
    "license": "LGPL-3",
    "depends": ["account", "account_batch_payment", "sale", "hr"],
    "data": [
        "data/account_payment_method_data.xml",
        "security/ir.model.access.csv",
        "views/account_payment/account_payment_views.xml",
        "views/sale_order/sale_order_views.xml",
        "views/hr_employee/hr_employee_views.xml",
        "wizards/deposit_wizard_views.xml",
        "wizards/account_payment_register_views.xml",
    ],
    "installable": True,
    "application": False,
}
