# Mock of C-Lightning Invoicing

This is a utility that will generate fake BOLT11 invoices in the manner of the c-lightning command line interface. It is stateful in that it will list issued invoices.

The objective is to enable regression/unit testing of application code that is driven by issued, paid and expired invoices.

Once an invoice is issued, the time can be 'advanced' with the `advancetimestamp` command such that invoices are appropriately treated as 'expired' without having to wait.

Also, an invoice can be marked paid with the `markpaid` command and they will be subsequently listed as paid.

This is a very simple implementation, more fleshed-out feature are easy to imagine, but this is the minimal necessary for my app's needs at present.

## Example Use

TODO

## Dependencies

This app uses code from https://github.com/rustyrussell/lightning-payencode to encode BOLT11 invoices, and hence has the same dependencies to be installed via `pip3`.

## License

None yet, but mainly because `lightining-payencode` is not yet licensed. The intention is to follow along with what is chosen for that project. FWIW, The author of this project prefers MIT licences for this type of thing.
