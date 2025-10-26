# Digital Ocean App Platform Deployment Guide

This guide will help you deploy the Tax Rates Intake Application to Digital Ocean App Platform.

## Prerequisites

1. A Digital Ocean account
2. Your Supabase credentials (URL and Service Key)
3. A generated SECRET_KEY for Flask

## Step 1: Generate SECRET_KEY

Run this command in your terminal to generate a secure SECRET_KEY:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Save the output - you'll need it for environment variables.

## Step 2: Create App in Digital Ocean

1. Log into Digital Ocean App Platform
2. Click "Create App"
3. Connect your GitHub repository: `https://github.com/osonwanne/cactuscomply-taxrates`
4. Select the branch (usually `main`)

## Step 3: Configure Environment Variables

In your Digital Ocean app settings, go to **Settings → App-Level Environment Variables** and add:

| Variable Name | Value | Type |
|--------------|-------|------|
| `SUPABASE_URL` | Your Supabase project URL (e.g., `https://xxx.supabase.co`) | Secret |
| `SUPABASE_SERVICE_KEY` | Your Supabase service role key (JWT token) | Secret |
| `SECRET_KEY` | Generated secret from Step 1 | Secret |

**Important:** Set all three as "Secret" type to encrypt them.

## Step 4: Configure Build and Run Commands

In your app settings, configure:

### Build Command
```bash
pip install -r requirements.txt
```
*(Or leave as "None" - Digital Ocean auto-detects this)*

### Run Command
```bash
gunicorn --bind 0.0.0.0:8080 --workers 4 app:app
```

**Critical:** 
- ✅ Use port `8080` (Digital Ocean's default health check port)
- ✅ Use `gunicorn` (production WSGI server)
- ❌ DO NOT use `python app.py` (development server)

## Step 5: Configure Health Check (if needed)

If you need to customize the health check:
- **Type:** HTTP
- **Path:** `/`
- **Port:** `8080`
- **Initial Delay:** 30 seconds

## Step 6: Deploy

1. Click "Save" to save your configuration
2. Digital Ocean will automatically build and deploy your app
3. Wait for the build to complete (usually 2-5 minutes)
4. Your app will be available at `https://your-app-name.ondigitalocean.app`

## Troubleshooting

### Health Check Failures

**Error:** `dial tcp xxx:8080: connect: connection refused`

**Solution:** Ensure your Run Command uses `--bind 0.0.0.0:8080`

### Development Server Warning

**Error:** `WARNING: This is a development server`

**Solution:** Make sure you're using the `gunicorn` command, not `python app.py`

### Environment Variables Not Found

**Error:** `Set SUPABASE_URL and SUPABASE_SERVICE_KEY in .env`

**Solution:** Verify environment variables are set in Digital Ocean App Platform settings

### Database Connection Issues

**Error:** Database connection failures

**Solution:** 
1. Verify your Supabase credentials are correct
2. Check that your Supabase project allows connections from Digital Ocean IPs
3. Ensure all required tables exist in your Supabase database

## Local Development vs Production

### Local Development
```bash
python app.py
```
- Runs on port 5000
- Uses `.env` file for configuration
- Debug mode enabled
- Development server

### Production (Digital Ocean)
```bash
gunicorn --bind 0.0.0.0:8080 --workers 4 app:app
```
- Runs on port 8080
- Uses environment variables from Digital Ocean
- Debug mode disabled
- Production WSGI server with 4 workers

## Required Tables in Supabase

Ensure these tables exist in your Supabase database:
- `jurisdictions`
- `rate_versions`
- `rates`
- `business_class_codes`
- `current_rates` (view)

## Support

If you encounter issues:
1. Check Digital Ocean build logs for errors
2. Verify all environment variables are set correctly
3. Ensure Supabase database tables are properly configured
4. Review application logs in Digital Ocean dashboard
