import json
import logging
from odoo import fields, models, api
from .settings import debug

logger = logging.getLogger(__name__)


class SaltJob(models.Model):
    _name = 'asterisk_plus.salt_job'
    _description = 'Salt job'

    fun = fields.Char()
    jid = fields.Char(required=True)
    ret = fields.Text()
    full_ret = fields.Text()
    success = fields.Char()
    res_model = fields.Char()
    res_method = fields.Char()
    pass_back = fields.Text()
    res_notify_uid = fields.Integer()

    @api.model
    def returner(self, ret):
        """Called by Salt returner.
        Example return: {
            'jid': '20210916150939079024',
            'return': True,
            'retcode': 0,
            'id': 'asterisk',
            'fun': 'test.ping',
            'success': True}
        """
        job = self.sudo().search([('jid', '=', ret['jid'])])
        if not job:
            logger.error('NO JOB FOUND FOR JID: %s', ret['jid'])
            return '{}: NOT FOUND'.format(ret['jid'])
        # Suppress file contents logging
        if ret.get('success', False) and job.fun in ['asterisk.get_file',
                'asterisk.get_config',
                'asterisk.get_all_configs']:
            debug(self, '{}: {}'.format(ret['jid'], list(ret['return'].keys())))
        else:
            debug(self, '{}: {}'.format(ret['jid'], ret['return']))
        # Check if return shoud be sent in notification box.
        if job.res_notify_uid:
            if ret.get('success', False):
                self.env['res.users'].asterisk_plus_notify(
                    '{}: {}'.format(ret['fun'], ret['return'] or 'OK'),
                    uid=job.res_notify_uid)
            else:
                self.env.user.asterisk_plus_notify(
                    '{}: {}'.format(ret['fun'], ret['return'] or 'FAIL'),
                    uid=job.res_notify_uid,
                    warning=True)

        # Check if return is sent to callback method.
        if job.res_model and job.res_method:
            method = getattr(self.env[job.res_model], job.res_method)
            res = method(ret['return'], json.loads(job.pass_back) if job.pass_back else None)
            return '{} {}: {}'.format(job.jid, job.res_method, res)
        else:
            return '{} return'.format(job.jid)
