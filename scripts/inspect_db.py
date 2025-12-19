import sqlite3
import sys

DB = 'db.sqlite3'
conn = sqlite3.connect(DB)
cur = conn.cursor()

print('Tables in', DB)
for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"):
    print(' -', row[0])

print('\nCheck for specific tables:')
for t in ['paystack_configurations', 'subscription_plans', 'payments', 'billing_payment']:
    cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name=?", (t,))
    r = cur.fetchone()
    if r:
        print(f"FOUND: {t}")
        print(r[1])
    else:
        print(f"MISSING: {t}")

print('\nApplied migrations (last 50):')
for row in cur.execute("SELECT app, name, applied FROM django_migrations ORDER BY applied DESC LIMIT 50;"):
    print(' -', row)

conn.close()
