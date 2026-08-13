# Shikshalokam Mohini Service – Local Setup

---

## Prerequisites

**macOS:**
* macOS
* Homebrew installed
* Python 3.10
* Git

**Linux:**
* Ubuntu 20.04+ (or Debian-based distro)
* `sudo` access
* Python 3.10
* Git

---

## 1. Install Python 3.10 and uv Dependency Manager

**macOS:**
```bash
brew install python@3.10
```

**Linux:**
```bash
sudo apt update
sudo apt install -y python3.10 python3.10-venv python3.10-dev python3-pip
```

Verify installation:
```bash
python3.10 --version
```

Install uv:
```bash
pip install uv
```

> ⚠️ On Linux, if `pip` doesn't point to Python 3.10, use `python3.10 -m pip install uv` instead.

---

## 2. Create a Virtual Environment (Outside Project Directory)

Assuming your project is located at:

**macOS:**
```
/Users/kunal/PycharmProjects/shikshalokam-mohini-service
```

**Linux:**
```
/home/<your-user>/projects/shikshalokam-mohini-service
```

### Step 1: Go to the project directory

**macOS:**
```bash
cd /Users/kunal/PycharmProjects/shikshalokam-mohini-service
```

**Linux:**
```bash
cd /home/<your-user>/projects/shikshalokam-mohini-service
```

### Step 2: Create the virtual environment
```bash
uv venv
```

### Step 3: Activate the virtual environment
```bash
source .venv/bin/activate
```

---

## 3. Install Project Dependencies

```bash
uv sync
```

---

## 4. Load Environment Variables

Make sure you have a `.env` file in the project root.

```bash
export $(cat .env | xargs)
```

> ⚠️ Note: This exports variables only for the current shell session.

---

## 5. Create `secrets.json`

The app reads secrets from `config/secrets.json`. Create the config directory and file:

```bash
mkdir -p config
nano config/secrets.json
```

Paste the content shared by your team. The file follows this structure:

```json
{
  "SECRET_KEY": "your-django-secret-key",
  "DATABASE_NAME": "mitra_db",
  "DATABASE_USER": "mitra_user",
  "DATABASE_PASSWORD": "mitra_password",
  "DATABASE_HOST": "localhost",
  "DATABASE_PORT": "5432"
}
```

> ℹ️ To see all keys the app expects, run:
> ```bash
> grep -n "SECRETS\[" shikshalokam_mohini/settings.py
> ```

---

## 6. Set Up Local PostgreSQL Database

### 6.1 Install PostgreSQL

**macOS:**
```bash
brew install postgresql@14
```

**Linux:**
```bash
sudo apt install -y postgresql postgresql-contrib ffmpeg
```

### 6.2 Start PostgreSQL

**macOS:**
```bash
brew services start postgresql@14
```

**Linux:**
```bash
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

Verify it's running:

**macOS:**
```bash
psql --version
```

**Linux:**
```bash
psql --version
sudo systemctl status postgresql
```

---

### 6.2 Create Database and User

Login to Postgres:

**macOS:**
```bash
psql postgres
```

**Linux:**
```bash
cd /tmp && sudo -u postgres psql
```

> ℹ️ On Linux, `cd /tmp` avoids a harmless "Permission denied" warning when switching to the postgres system user.

Create a database user:
```sql
CREATE USER mitra_user WITH PASSWORD 'mitra_password';
```

Create the database:
```sql
CREATE DATABASE mitra_db OWNER mitra_user;
```

Grant privileges:
```sql
GRANT ALL PRIVILEGES ON DATABASE mitra_db TO mitra_user;
```

Exit psql:
```sql
\q
```

---

### 6.3 Update `.env` File

Add or update the following variables in your `.env` file:

```env
DATABASE_NAME=mitra_db
DATABASE_USER=mitra_user
DATABASE_PASSWORD=mitra_password
DATABASE_HOST=localhost
DATABASE_PORT=5432
```

### 6.4 Install PostgreSQL Python Driver

Make sure this dependency exists (usually already in `requirements.in`):

```bash
uv pip install psycopg2-binary
```

**Linux only** — if you get build errors, install system headers first:
```bash
sudo apt install -y libpq-dev gcc
```

Then retry the install.

---

### 6.5 Run Django Migrations

Ensure your virtual environment is active and env vars are loaded:

```bash
export $(cat .env | xargs)
```

Run migrations:

```bash
python3 manage.py migrate
```

(Optional) Create a superuser:

You can accept the default name and give any password, keep email
empty and just press enter till completed.

```bash
python3 manage.py createsuperuser
```

### 6.6 Seed Initial Data

After migrations, run the following command to insert the required initial data into the database:

```bash
python3 manage.py prepare_db
```

---

## Common Issues

**Postgres not starting**

macOS:
```bash
brew services restart postgresql@14
```

Linux:
```bash
sudo systemctl restart postgresql
```

**Role does not exist**

macOS:
```bash
psql postgres
\du
```

Linux:
```bash
sudo -u postgres psql
\du
```

**Port conflict**

macOS:
```bash
lsof -i :5432
```

Linux:
```bash
sudo lsof -i :5432
# or
ss -tulpn | grep 5432
```

**Peer authentication error (Linux only)**

If you see `FATAL: Peer authentication failed for user "mitra_user"`, edit `pg_hba.conf`:

```bash
sudo nano /etc/postgresql/14/main/pg_hba.conf
```

Find the `local` line and change `peer` to `md5`:

```
# Before
local   all             all                                     peer

# After
local   all             all                                     md5
```

Then restart:
```bash
sudo systemctl restart postgresql
```

---

## 7. Run the Application Server

```bash
uvicorn shikshalokam_mohini.asgi:application \
  --host 0.0.0.0 \
  --port 9000 \
  --workers 4 \
  --ws-ping-interval 30 \
  --ws-ping-timeout 300 \
  --reload
```

---

## 8. Run Celery Worker

Open a new terminal (with the same virtual environment activated):

```bash
celery -A shikshalokam_mohini worker --pool=threads
```

---

## Notes

* Ensure Redis or any other required backing services are running before starting Celery.
* Always activate `.venv` before running server or worker commands.

---

## 9. Set Up Redis (Local, IF celery gives error)

Redis is required for Celery and background task processing.

---

### 9.1 Install Redis

**macOS:**
```bash
brew install redis
```

**Linux:**
```bash
sudo apt install -y redis-server
```

---

### 9.2 Start Redis Server

**macOS:**
```bash
brew services start redis
```

**Linux:**
```bash
sudo systemctl start redis
sudo systemctl enable redis
```

---

### 9.3 Verify Redis Is Running

```bash
redis-cli ping
```

Expected output:

```text
PONG
```

---

## Common Redis Issues

**Redis not running**

macOS:
```bash
brew services restart redis
```

Linux:
```bash
sudo systemctl restart redis
```

**Port already in use**

macOS:
```bash
lsof -i :6379
```

Linux:
```bash
sudo lsof -i :6379
# or
ss -tulpn | grep 6379
```

---

## 10. Post-Setup: Configure Admin User Password

Once the service is up and running, set the password for the default admin account via the Django admin panel.

1. Open the admin panel in your browser:
   ```
   http://localhost:9000/admin
   ```

2. Navigate to the **Profiles** section

3. Find the user: **null@shikshalokam.org**

4. Set the password to: `grit@123`

> ⚠️ This step is required before using the service — the default account won't be accessible otherwise.

## 11. Post-Setup: Create Company Bots
 
Once the admin password is configured, import company data and create a company bot.
 
1. Download the sample CSV from Google Drive:
```
   https://drive.google.com/file/d/1I799a5xpcgmQMPPfE7EdFI_Ot3ufiasE/view?usp=sharing
```
   Locate the sample company/bot import template and download it locally.
 
2. In the  admin panel, navigate to the **Company Bots**  section:
```
   http://localhost:9000/admin/chatbot/companybot/
```
 
3. Use the **Import Bot** action and upload the downloaded JSON to create an company Bot.

4. Verify the bot appears in the CompanyBot list and is linked to the correct flow route before testing.
 