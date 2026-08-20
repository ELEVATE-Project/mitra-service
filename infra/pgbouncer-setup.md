# PgBouncer Setup (per EC2 instance)

## Install

```bash
sudo apt install pgbouncer
```

## Configure

```bash
sudo cp infra/pgbouncer.ini.template /etc/pgbouncer/pgbouncer.ini
# Fill in DATABASE_NAME, DATABASE_HOST, DATABASE_PORT
sudo nano /etc/pgbouncer/pgbouncer.ini
```

## Create userlist

Generate md5 hash: `echo -n "<password><username>" | md5sum` then prefix result with `md5`.

```bash
sudo nano /etc/pgbouncer/userlist.txt
```

File contents:
```
"<DATABASE_USER>" "md5<hash>"
```

## Enable and start

```bash
sudo systemctl enable pgbouncer
sudo systemctl start pgbouncer
```

## Verify

```bash
psql -h 127.0.0.1 -p 6432 -U <DATABASE_USER> <DATABASE_NAME>
```

## Monitor pool stats

```bash
psql -h 127.0.0.1 -p 6432 -U <DATABASE_USER> pgbouncer -c "SHOW POOLS;"
```
