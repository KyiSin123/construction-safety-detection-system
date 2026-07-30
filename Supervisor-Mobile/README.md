# PPE Supervisor Mobile

The Expo app receives PPE violations and attendance correction requests assigned to the signed-in supervisor. Supervisors can resolve PPE cases and approve or reject exact worker-requested attendance times.

## Local setup

1. Copy `.env.example` to `.env` and set `EXPO_PUBLIC_API_BASE_URL` to the HTTPS address of the Flask server. Do not use `localhost` for a physical phone.
2. Run `npm install` and then `npx expo start` from this directory.
3. Create an Expo/EAS project, replace `REPLACE_WITH_YOUR_EAS_PROJECT_ID` in `app.json`, and use an EAS development build to test remote notifications.

The Flask server must set `SUPERVISOR_JWT_SECRET` and bootstrap the first administrator with `SUPERVISOR_INITIAL_ADMIN_USERNAME` and `SUPERVISOR_INITIAL_ADMIN_PASSWORD`. Sign in at `/supervisors` to create supervisor accounts and assignments.

## How to run
For web,
npx expo start -c --web
