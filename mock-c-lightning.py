#! /usr/bin/env python3

import os
import sys
import argparse
import json
import time
import tempfile
import hashlib

from binascii import unhexlify
from lightning_payencode.lnaddr import lnencode, lndecode, LnAddr

STATE_FILE = os.path.join(tempfile.gettempdir(), "mock-c-lightning-state.json")

# This key is used as the private key for signing the invoices. Security isn't
# the goal in this application, so it is fine to use any old number.
SIGNING_KEY = "0000111122223333444455556666777788889999aaaabbbbccccddddeeeeffff"

SATOSHIS_PER_BTC = 100000000
MSATOSHIS_PER_BTC = SATOSHIS_PER_BTC * 1000

# for scale testing bolt11s take a noticeable chunk of time to encode. If it
# isn't important that it be correct , we can short-circuit and just return a
# placeholder.
MOCK_BOLT11 = "lnbc50n1pdm373mpp50hlcjdrcm9u3qqqs4a926g63d3t5qwyndytqjjgknskuvmd9kc2sdz2d4shyapwwpujq6twwehkjcm9ypnx7u3qxys8q6tcv4k8xtpqw4ek2ujlwd68y6twvuazqg3zyqxqzjcuvzstexcj4zcz7ldtkwz8t5pdsghauyhkdqdxccx8ts3ta023xqzwgwxuvlu9eehh97d0qcu9k5a4u2glenrekp7w9sswydl4hneyjqqzkxf54"

###############################################################################

class DaemonState(dict):
    def __init__(self, in_memory):
        super().__init__()
        self.in_memory = in_memory
        if in_memory:
            self.update(DaemonState.empty_state())
        else:
            self.update(DaemonState.read_state())


    def empty_state():
        return {'time_offset':             0,
                'autoclean_cycle_seconds': 0,
                'autoclean_last_clean':    None,
                'autoclean_expired_by':    86400,
                'invoices':                []}

    def read_state():
        if os.path.exists(STATE_FILE):
            f = open(STATE_FILE, 'r')
            content = f.read()
            f.close()
            return json.loads(content)
        return DaemonState.empty_state()

    def write_state(self):
        if self.in_memory:
            return
        f = open(STATE_FILE, 'w')
        f.write(json.dumps(self, sort_keys=True, indent=1))
        f.close()

    def reset(self):
        self.update(DaemonState.empty_state())

###############################################################################

class MockDaemon(object):
    def __init__(self, in_memory, mock_bolt11=False):
        self.state = DaemonState(in_memory)
        self.mock_bolt11 = mock_bolt11

    ###########################################################################

    def _get_time(self):
        return int(time.time()) + self.state['time_offset']

    ###########################################################################

    def _gen_bolt11(self, args, payment_hash):
        addr = LnAddr()
        addr.currency = 'bc'
        addr.failback = None
        addr.amount = args.msatoshi / MSATOSHIS_PER_BTC
        addr.date = self._get_time()
        addr.paymenthash = unhexlify(payment_hash)
        addr.tags.append(('d', args.description))
        addr.tags.append(('x', str(args.expiry)))
        return (MOCK_BOLT11 if self.mock_bolt11 else
                lnencode(addr, SIGNING_KEY))

    def _get_payment_hash(self, preimage):
        # return the sha256 digest string of the preimage bytes
        preimage_bytes = bytes.fromhex(preimage)
        return hashlib.sha256(preimage_bytes).hexdigest()

    def _new_invoice(self, args):
        payment_hash = self._get_payment_hash(args.preimage)
        bolt11 = self._gen_bolt11(args, payment_hash)
        now = self._get_time()
        return {"label":        args.label,
                "bolt11":       bolt11,
                "payment_hash": payment_hash,
                "msatoshi":     args.msatoshi,
                "status":       "unpaid",
                "expires_at":   now + args.expiry,
                "expiry_time":  now + args.expiry
               }

    def invoice(self, args):
        labels = set(i['label'] for i in self.state['invoices'])
        if args.label in labels:
            sys.exit("*** label already in set?")
        i = self._new_invoice(args)
        self.state['invoices'].append(i)
        self.state.write_state()
        output = {'payment_hash': i['payment_hash'],
                  'expiry_time':  i['expiry_time'],
                  'expires_at':   i['expires_at'],
                  'bolt11':       i['bolt11'],
                 }
        return output

    ###########################################################################

    def _iter_remaining(self, now):
        for i in self.state['invoices']:
            if i['status'] != 'expired':
                yield i
            expired_for = now - i['expiry_time']
            if expired_for < state['autoclean_expired_by']:
                yield i

    def _autoclean(self, now):
        if self.state['autoclean_cycle_seconds'] == 0:
            return
        elapsed = now - self.state['autoclean_last_clean']
        if elapsed < self.state['autoclean_cycle_seconds']:
            return

        for i in self.state['invoices']:
            if i['status'] != 'expired':
                continue
        self.state['invoices'] = list(self._iter_remaining(now))
        self.state['autoclean_last_clean'] = now


    def listinvoices(self, args):
        timestamp = self._get_time()
        for i in self.state['invoices']:
            if i['status'] != 'unpaid':
                continue
            if timestamp > i['expires_at']:
                i['status'] = "expired"
        self._autoclean(timestamp)
        self.state.write_state()
        return self.state['invoices']

    ###########################################################################

    def autocleaninvoice(self, args):
        timestamp = self._get_time()
        self.state['autoclean_cycle_seconds'] = args.cycle_seconds
        self.state['autoclean_last_clean'] = timestamp
        self.state['autoclean_expired_by'] = args.expired_by
        self.state.write_state()
        return None

    ###########################################################################

    def delinvoice(self, args):
        invoice = None
        for i in self.state['invoices']:
            if i['label'] == args.label:
                invoice = i
                break
        if not invoice:
            return { "code" : -1, "message" : "Unknown invoice" }
        if invoice['status'] != args.status:
            return { "code" : -1, "message" : "Wrong status" }
        self.state['invoices'] = [i for i in self.state['invoices'] if
                                  i['label'] != args.label]
        self.state.write_state()
        return None

    ###########################################################################

    def _get_next_pay_index(self):
        i_list = [i['pay_index'] for i in self.state['invoices']
                  if i['status'] == 'paid']
        current_max = max(i_list) if len(i_list) > 0 else 0
        return current_max + 1

    def _set_paid(self, i):
        pay_index = self._get_next_pay_index()
        i['status'] = "paid"
        i['paid_at'] = self._get_time()
        i['paid_timestamp'] = self._get_time()
        # add some fees arbitrarily, so it looks more like a real node
        i['msatoshi_recieved'] = i['msatoshi'] + 33
        i['pay_index'] = pay_index

    def markpaid(self, args):
        for i in self.state['invoices']:
            if i['label'] == args.label:
                self._set_paid(i)
                self.state.write_state()
                return None
        return { "code" : -1, "message" : "unknown invoice" }

    ###########################################################################

    def advancetime(self, args):
        self.state['time_offset'] = self.state['time_offset'] + args.seconds
        self.state.write_state()
        return None

    ###########################################################################

    def reset(self, args):
        self.state.reset()
        self.state.write_state()
        return None

    ###########################################################################

    def run_cmd_old(self, args):
        cmds = {'invoice':          self.invoice,
                'listinvoices':     self.listinvoices,
                'autocleaninvoice': self.autocleaninvoice,
                'delinvoce':        self.delinvoice,
                'markpaid':         self.markpaid,
                'advancetime':      self.advancetime,
                'reset':            self.reset,
               }
        return cmds[args.cmd](args)

    def run_cmd(self, argv):
        parser = argparse.ArgumentParser(description='mock c-lightning')
        subparsers = parser.add_subparsers(dest='subparser_name',
                                           help='sub-command help')

        # invoice:
        parser_inv = subparsers.add_parser('invoice', help='invoice help')
        parser_inv.add_argument('msatoshi', type=int, help='msatoshi amount')
        parser_inv.add_argument('label', help='label string of invoice')
        parser_inv.add_argument('description',
                                 help='description string for bolt11 invoice')
        parser_inv.add_argument('expiry', type=int,
                                 help='seconds until invoice expiry')
        parser_inv.add_argument('preimage',
                                 help='preimage value')
        parser_inv.set_defaults(cmd=self.invoice)

        # listinvoices:
        parser_list = subparsers.add_parser('listinvoices',
                                            help='listinvoices help')
        parser_list.add_argument('--label', help='label string of invoice')
        parser_list.set_defaults(cmd=self.listinvoices)

        # autocleaninvoice:
        parser_clean = subparsers.add_parser('autocleaninvoice',
                                             help='autocleaninvoice help')
        parser_clean.add_argument('--cycle-seconds', type=int, default=3600,
                                 help=('Perform cleanup every {cycle_seconds} '
                                       '(default 3600), or disable autoclean '
                                       'if 0'))
        parser_clean.add_argument('--expired-by', type=int, default=86400,
                                 help=('Clean up expired invoices that have '
                                       'expired for {expired_by} seconds '
                                       '(default 86400).'))
        parser_clean.set_defaults(cmd=self.autocleaninvoice)

        # delinvoice:
        parser_list = subparsers.add_parser('delinvoice',
                                            help=('Delete invoice {label} with'
                                                  ' {status}'))
        parser_list.add_argument('label', type=str,
                                 help='label string of invoice')
        parser_list.add_argument('status', type=str,
                                 choices=['paid', 'unpaid', 'expired'],
                                 help='status of invoice')
        parser_list.set_defaults(cmd=self.delinvoice)

        # markpaid (not c-lightning cmd):
        parser_paid = subparsers.add_parser('markpaid', help='markpaid help')
        parser_paid.add_argument('label', help='label string of invoice')
        parser_paid.set_defaults(cmd=self.markpaid)

        # advancetime (not c-lightning cmd):
        parser_advancetime = subparsers.add_parser('advancetime',
                                                   help='advancetime help')
        parser_advancetime.add_argument('seconds', type=int,
                                        help='seconds to advance time offset')
        parser_advancetime.set_defaults(cmd=self.advancetime)

        # reset (not c-lightning cmd):
        parser_reset = subparsers.add_parser('reset', help='reset help')
        parser_reset.set_defaults(cmd=self.reset)

        args = parser.parse_args(argv)
        if not args.subparser_name:
            parser.print_help()
            return None
        return args.cmd(args)


###############################################################################

if __name__ == "__main__":
    daemon = MockDaemon(False)
    output = daemon.run_cmd(sys.argv[1:])
    if output:
        print(json.dumps(output, indent=2, sort_keys=True))
    if (type(output) is list) and (len(output) == 0):
        print("[]")
