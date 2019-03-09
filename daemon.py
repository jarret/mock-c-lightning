import sys
import uuid
import json
import subprocess
import random
from hashlib import sha256
from base64 import b64encode

from lightning import LightningRpc


EXPIRY_SECONDS = 10 * 60

class Daemon(object):
    """
    C lightining demon
    """
    def __init__(self):
        pass

    def _gen_preimage(self):
        # I didn't actually test this in the mock-c-ligtning repot
        return sha256(random.getrandbits(256)).hexdigest()

    def _calc_payment_hash(self, preimage):
        preimage_bytes = bytes.fromhex(preimage)
        return sha256(preimage_bytes).hexdigest()

    def _gen_description_str(self):
        return "a description string for this invoice"

    def _gen_new_label(self):
        label_bytes = uuid.uuid4().bytes
        label_str = b64encode(label_bytes).decode('utf8')
        return label_str, label_bytes

    def invoice_c_lightning(self, msatoshi, label, description, expiry,
                            preimage):
        sys.exit("implement this in the subclass")

    def get_c_lightning_invoices(self):
        sys.exit("implement this in the subclass")

    def create_new_invoice(self):
        label_str, label_bytes = self._gen_new_label()
        preimage = self._gen_preimage()
        payment_hash = self._calc_payment_hash(preimage)
        description = self._gen_description_str()
        msatoshi = 10000
        expiry = EXPIRY_SECONDS

        return self.invoice_c_lightning(msatoshi, label_str, description,
                                        expiry, preimage)


###############################################################################

SATOSHIS_PER_BTC = 100000000
MSATOSHIS_PER_BTC = SATOSHIS_PER_BTC * 1000

def get_exitcode_stdout_stderr(cmd):
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = proc.communicate()
    exitcode = proc.returncode
    return exitcode, out, err

###############################################################################

class CliMockDaemon(Daemon):

    """ calls to mock-c-lightning.py to invoice """
    def invoice_c_lightning(self, msatoshi, label, description, expiry,
                            preimage):

        print("invoice cli")
        path = self.settings.lightning_rpc
        cmd = [path, 'invoice', str(msatoshi), label, description,
               str(expiry), preimage]
        code, out, err = get_exitcode_stdout_stderr(cmd)
        if code != 0:
            return None, err.decode('utf8')
        o = out.decode('utf8')
        return json.loads(o), None

    def get_c_lightning_invoices(self):
        path = self.settings.lightning_rpc
        cmd = [path, 'listinvoices']
        code, out, err = get_exitcode_stdout_stderr(cmd)
        if code != 0:
            return None, err.decode('utf8')
        o = out.decode('utf8')
        print(o)
        return json.loads(o)['invoices'], None

    def reset(self):
        path = self.settings.lightning_rpc
        cmd = [path, 'reset']
        code, out, err = get_exitcode_stdout_stderr(cmd)
        if code != 0:
            return None, err.decode('utf8')
        return None, None

    def autoclean(self):
        path = self.settings.lightning_rpc
        cmd = [path, 'autocleaninvoice', '--cycle-seconds', '60',
               '--expired-by', '10']
        code, out, err = get_exitcode_stdout_stderr(cmd)
        if code != 0:
            return None, err.decode('utf8')
        return None, None

    def advance_time(self, seconds):
        path = self.settings.lightning_rpc
        cmd = [path, 'advancetime', str(seconds)]
        code, out, err = get_exitcode_stdout_stderr(cmd)
        if code != 0:
            return None, err.decode('utf8')
        return None, None

    def mark_paid(self, label):
        path = self.settings.lightning_rpc
        cmd = [path, 'markpaid', label]
        code, out, err = get_exitcode_stdout_stderr(cmd)
        if code != 0:
            return None, err.decode('utf8')
        return None, None

    def delete(self, label, state='paid'):
        path = self.settings.lightning_rpc
        # TODO state?
        cmd = [path, 'delete', label]
        code, out, err = get_exitcode_stdout_stderr(cmd)
        if code != 0:
            return None, err.decode('utf8')
        return None, None


###############################################################################

class MemMockDaemon(Daemon):
    """ calls in-memory mock C lighting to invoice """

    def __init__(self):
        super().__init__()

    def punch_daemon(self, daemon):
        self.daemon = daemon

    def invoice_c_lightning(self, msatoshi, label, description, expiry,
                            preimage):
        print("invoice mem mock")
        cmd = ['invoice', str(msatoshi), label, description,
               str(expiry), preimage]
        output = self.daemon.run_cmd(cmd)
        return output, None

    def get_c_lightning_invoices(self):
        cmd = ['listinvoices']
        output = self.daemon.run_cmd(cmd)
        return output['invoices'], None

    def reset(self):
        cmd = ['reset']
        output = self.daemon.run_cmd(cmd)
        return output, None

    def autoclean(self):
        cmd = ['autocleaninvoice', '--cycle-seconds', '60',
               '--expired-by', '10']
        output = self.daemon.run_cmd(cmd)
        return output, None

    def advance_time(self, seconds):
        cmd = ['advancetime', str(seconds)]
        output = self.daemon.run_cmd(cmd)
        return output, None

    def mark_paid(self, label):
        cmd = ['markpaid', label]
        output = self.daemon.run_cmd(cmd)
        return output, None

    def delete(self, label, state='paid'):
        cmd = ['delinvoice', label, state]
        output = self.daemon.run_cmd(cmd)
        return output, None


###############################################################################

class RealDaemon(Daemon):
    """ calls c-lightning via the rpc """
    def __init__(self, path):
        super().__init__()
        self.path = path
        print("rpc path: %s" % self.path)
        self.rpc = LightningRpc(self.path)

    def invoice_c_lightning(self, msatoshi, label, description, expiry,
                            preimage):
        print("invoice real")
        try:
            result = self.rpc.invoice(msatoshi, label, description,
                                      expiry=expiry, preimage=preimage)
        except:
            return None, "c-lightning invoice exception"
        print(json.dumps(result, indent=1, sort_keys=True))
        return result, None

    def get_c_lightning_invoices(self):
        try:
            result = self.rpc.listinvoices()
        except:
            return None, "c-lightning listinvoices exception"

        print(json.dumps(result, indent=1, sort_keys=True))
        return result['invoices'], None

    def delete(self, label, state='paid'):
        try:
            result = self.rpc.delinvoice(label, state)
        except:
            return None, "c-lightning delinvoice exception"
        print(json.dumps(result, indent=1, sort_keys=True))
        return result, None
