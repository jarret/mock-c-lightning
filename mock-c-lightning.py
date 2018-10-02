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

###############################################################################

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
        return empty_state() if len(content) == 0 else json.loads(content)
    return empty_state()

def write_state(s):
    f = open(STATE_FILE, 'w')
    f.write(json.dumps(s, sort_keys=True, indent=1))
    f.close()


def get_time(state):
    return int(time.time()) + state['time_offset']


###############################################################################

def gen_bolt11(state, args, payment_hash):
    addr = LnAddr()
    addr.currency = 'bc'
    addr.failback = None
    addr.amount = args.msatoshi / MSATOSHIS_PER_BTC
    addr.date = get_time(state)
    addr.paymenthash = unhexlify(payment_hash)
    addr.tags.append(('d', args.description))
    addr.tags.append(('x', str(args.expiry)))
    return lnencode(addr, SIGNING_KEY)

def get_next_pay_index(state):
    i_list = [i['pay_index'] for i in state['invoices']
              if i['status'] == 'paid']
    current_max = max(i_list) if len(i_list) > 0 else 0
    return current_max + 1


def get_payment_hash(preimage):
    # return the sha256 digest string of the preimage bytes
    preimage_bytes = bytes.fromhex(preimage)
    return hashlib.sha256(preimage_bytes).hexdigest()

def new_invoice(state, args):
    payment_hash = get_payment_hash(args.preimage)
    bolt11 = gen_bolt11(state, args, payment_hash)
    now = get_time(state)
    return {"label":        args.label,
            "bolt11":       bolt11,
            "payment_hash": payment_hash,
            "msatoshi":     args.msatoshi,
            "status":       "unpaid",
            "expires_at":   now + args.expiry,
            "expiry_time":  now + args.expiry
           }

###############################################################################

def set_expired(i):
    i['status'] = "expired"


def set_paid(state, i):
    pay_index = get_next_pay_index(state)
    i['status'] = "paid"
    i['paid_at'] = get_time(state)
    i['paid_timestamp'] = get_time(state)
    # add some fees arbitrarily, so it looks more like a real node
    i['msatoshi_recieved'] = i['msatoshi'] + 33
    i['pay_index'] = pay_index


def iter_remaining(now, state):
    for i in state['invoices']:
        if i['status'] != 'expired':
            yield i
        expired_for = now - i['expiry_time']
        if expired_for < state['autoclean_expired_by']:
            yield i


def autoclean(now, state):
    if state['autoclean_cycle_seconds'] == 0:
        return
    elapsed = now - state['autoclean_last_clean']
    if elapsed < state['autoclean_cycle_seconds']:
        return

    for i in state['invoices']:
        if i['status'] != 'expired':
            continue
    state['invoices'] = list(iter_remaining(now, state))
    state['autoclean_last_clean'] = now

###############################################################################

def invoice_cmd(args):
    state = read_state()
    labels = set(i['label'] for i in state['invoices'])
    if args.label in labels:
        sys.exit("*** label already in set?")
    i = new_invoice(state, args)
    state['invoices'].append(i)
    write_state(state)
    output = {'payment_hash': i['payment_hash'],
              'expiry_time':  i['expiry_time'],
              'expires_at':   i['expires_at'],
              'bolt11':       i['bolt11'],
             }
    print(json.dumps(output, sort_keys=True, indent=2))


def listinvoices_cmd(args):
    #print(int(time.time()))
    state = read_state()
    timestamp = get_time(state)
    #print(timestamp)
    for i in state['invoices']:
        if i['status'] != 'unpaid':
            continue
        if timestamp > i['expires_at']:
            set_expired(i)
    autoclean(timestamp, state)
    write_state(state)
    print(json.dumps(state['invoices'], indent=2, sort_keys=True))


def autoclean_cmd(args):
    state = read_state()
    timestamp = get_time()
    state['autoclean_cycle_seconds'] = args.cycle_seconds
    state['autoclean_last_clean'] = timestamp
    state['autoclean_expired_by'] = args.expired_by
    write_state(state)


def markpaid_cmd(args):
    state = read_state()
    for i in state['invoices']:
        if i['label'] == args.label:
            set_paid(state, i)
            write_state(state)
            return
    sys.exit("*** label not found?")


def reset_cmd(args):
    state = empty_state()
    write_state(state)


def advancetime_cmd(args):
    state = read_state()
    state['time_offset'] = state['time_offset'] + args.seconds
    write_state(state)

###############################################################################

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
parser_inv.set_defaults(func=invoice_cmd)

# listinvoices:
parser_list = subparsers.add_parser('listinvoices', help='listinvoices help')
parser_list.add_argument('--label', help='label string of invoice')
parser_list.set_defaults(func=listinvoices_cmd)

# autocleaninvoice:
parser_clean = subparsers.add_parser('autocleaninvoice', help='autocleaninvoice help')
parser_clean.add_argument('--cycle-seconds', type=int, default=3600,
                         help=('Perform cleanup every {cycle_seconds} '
                               '(default 3600), or disable autoclean if 0'))
parser_clean.add_argument('--expired-by', type=int, default=86400,
                         help=('Clean up expired invoices that have expired '
                               'for {expired_by} seconds (default 86400).'))
parser_clean.set_defaults(func=autoclean_cmd)


# markpaid (not c-lightning cmd):
parser_paid = subparsers.add_parser('markpaid', help='markpaid help')
parser_paid.add_argument('label', help='label string of invoice')
parser_paid.set_defaults(func=markpaid_cmd)

# reset (not c-lightning cmd):
parser_reset = subparsers.add_parser('reset', help='reset help')
parser_reset.set_defaults(func=reset_cmd)

# advancetime (not c-lightning cmd):
parser_advancetime = subparsers.add_parser('advancetime',
                                           help='advancetime help')
parser_advancetime.add_argument('seconds', type=int,
                                help='seconds to advance time offset')
parser_advancetime.set_defaults(func=advancetime_cmd)


if __name__ == "__main__":

    args = parser.parse_args()
    if not args.subparser_name:
        parser.print_help()
    else:
        args.func(args)

