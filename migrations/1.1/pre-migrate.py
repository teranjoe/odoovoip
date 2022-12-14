from odoo.tools.sql import rename_column


def migrate(cr, version):
    rename_column(cr, 'asterisk_plus_call', 'called_user', 'answered_user')
    rename_column(cr, 'asterisk_plus_recording', 'called_user', 'answered_user')
