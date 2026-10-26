"""One local captured-data inspection run; no downloads or dataset admission."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

from .alpaca_calendar import AlpacaCalendarStore
from .captured_observations import inspect_captures
from .contracts import ContractError
from .lean_smoke import prepare, run_prepared


@contextmanager
def readonly_captures(database):
    """Use existing capture read APIs without constructors/migrations/writes."""
    path=Path(database).resolve()
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    store=AlpacaCalendarStore.__new__(AlpacaCalendarStore)
    store.db=db
    try:yield store
    finally:db.close()


def prepare_captured(directory,*,database,price_source_id,price_import_id,calendar_source_id,calendar_import_id,listing_id,clock=None):
    with readonly_captures(database) as store:
        report=inspect_captures(store,price_source_id=price_source_id,price_import_id=price_import_id,
            calendar_source_id=calendar_source_id,calendar_import_id=calendar_import_id,
            listing_id=listing_id,clock=clock)
    result=prepare(directory,inspection_report=report)
    return dict(result,inspection_only=True,dataset_admitted=False,training_ready=False,
        expected_group_count=len(report['observation_groups']),calendar_venue_matches_listing=report['calendar_venue_matches_listing'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare-run'])
    for name in ('database','price-source','price-import','calendar-source','calendar-import','listing','out'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--timeout',type=int,default=300)
    parser.add_argument('--prepare-only',action='store_true')
    args=parser.parse_args()
    try:
        result=prepare_captured(Path(args.out),database=args.database,price_source_id=args.price_source,
            price_import_id=args.price_import,calendar_source_id=args.calendar_source,
            calendar_import_id=args.calendar_import,listing_id=args.listing)
        if not args.prepare_only:result=run_prepared(args.out,timeout=args.timeout)
    except (ContractError,OSError,ValueError,sqlite3.Error) as error:
        parser.exit(2,f'Captured inspection rejected: {error}\n')
    print(json.dumps(result,sort_keys=True,indent=2))


if __name__=='__main__':main()
