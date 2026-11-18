"""DOBBY V1 — local simulation CLI; no network or subprocess execution."""
import argparse
import asyncio
import json
from bridge import Limits, Orchestrator, Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='bridge.sqlite3')
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('create')
    create.add_argument('task')
    for name in ('run', 'approve', 'show', 'recover'):
        p = sub.add_parser(name)
        p.add_argument('id')
    args = parser.parse_args()
    store = Store(args.db)
    if args.command == 'create':
        print(store.create(args.task, Limits()))
        return
    if args.command == 'approve':
        store.approve(args.id)
    elif args.command == 'recover':
        store.recover_interrupted(args.id)
    elif args.command == 'run':
        asyncio.run(Orchestrator(store).run(args.id))
    print(json.dumps({'mission': store.get(args.id), 'messages': store.messages(args.id)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
