# Shikshalokam Mohini Service – Local Setup
---

## Prerequisites

* macOS
* Homebrew installed
* Python 3.10
* Git

---

## 1. Install Python 3.10

```bash
brew install python@3.10
```

Verify installation:

```bash
python3.10 --version
```

---

## 2. Create a Virtual Environment (Outside Project Directory)

Assuming your project is located at:

```
/Users/kunal/PycharmProjects/shikshalokam-mohini-service
```

### Step 1: Go to the parent directory

```bash
cd /Users/kunal/PycharmProjects/
```

### Step 2: Create the virtual environment

```bash
python3.10 -m venv mitra_env
```

### Step 3: Activate the virtual environment

```bash
source mitra_env/bin/activate
```

---

## 3. Navigate to the Project Directory

```bash
cd shikshalokam-mohini-service
```

---

## 4. Install `uv`

```bash
pip install uv
```

---

## 5. Install Project Dependencies

```bash
uv pip install -r requirements.in --upgrade
```

---

## 6. Load Environment Variables

Make sure you have a `.env` file in the project root.

```bash
export $(cat .env | xargs)
```

> ⚠️ Note: This exports variables only for the current shell session.

---

## 7. Set Up Local PostgreSQL Database

### 7.1 Install PostgreSQL

Using Homebrew:

```bash
brew install postgresql@14
```

Start PostgreSQL:

```bash
brew services start postgresql@14
```

Verify it’s running:

```bash
psql --version
```

---

### 7.2 Create Database and User

Login to Postgres:

```bash
psql postgres
```

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

### 7.3 Update `.env` File

Add or update the following variables in your `.env` file:

```env
DATABASE_NAME=mitra_db
DATABASE_USER=mitra_user
DATABASE_PASSWORD=mitra_password
DATABASE_HOST=localhost
DATABASE_PORT=5432
```

### 7.4 Install PostgreSQL Python Driver

Make sure this dependency exists (usually already in `requirements.in`):

```bash
uv pip install psycopg2-binary
```

---

### 7.5 Run Django Migrations

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

---

## Common Issues

**Postgres not starting**

```bash
brew services restart postgresql@14
```

**Role does not exist**

```bash
psql postgres
\du
```

**Port conflict**

```bash
lsof -i :5432
```


## 8. Run the Application Server

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

## 9. Run Celery Worker

Open a new terminal (with the same virtual environment activated):

```bash
celery -A shikshalokam_mohini worker --pool=threads
```

---

## Notes

* Ensure Redis or any other required backing services are running before starting Celery.
* Always activate `mitra_env` before running server or worker commands.

---

Perfect, let’s plug **Redis setup** into the README cleanly 👌
You can add this as the next section.

---

## 10. Set Up Redis (Local, IF celery gives error)

Redis is required for Celery and background task processing.

---

### 10.1 Install Redis

Using Homebrew:

```bash
brew install redis
```

---

### 10.2 Start Redis Server

Start Redis as a background service:

```bash
brew services start redis
```
---

### 10.3 Verify Redis Is Running

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

```bash
brew services restart redis
```

**Port already in use**

```bash
lsof -i :6379
```
