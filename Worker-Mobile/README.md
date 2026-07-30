# PPE Worker Mobile

The worker app shows the signed-in worker's PPE violation history, attendance history and correction requests, and contact profile.

## Local setup

1. Set `EXPO_PUBLIC_API_BASE_URL` in `.env` to the Flask server address reachable from the phone.
2. Run `npm install` and `npx expo start`.
3. Sign in with a worker ID and password created from the admin site or the demo seeder.

## Demo account

From `D:\Detection\src`, run:

```powershell
..\.venv\Scripts\python.exe seed_worker_demo.py
```

The deterministic development credentials are `DEMO-WORKER` / `Demo1234`. The seeder assigns the account to the first active supervisor when one exists. Remove only its demo data with:

```powershell
..\.venv\Scripts\python.exe seed_worker_demo.py --cleanup
```
