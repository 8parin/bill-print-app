# Deploy to Render

## Prerequisites
- Render account (free tier works)
- Neon DB account (free tier works)

## Step 1: Set up Neon DB

1. Go to https://console.neon.tech
2. Create a new project (or use existing)
3. Copy the connection string (looks like:
   `postgresql://username:password@host.neon.tech/database?sslmode=require`)

## Step 2: Deploy to Render

### Option A: Deploy via Dashboard

1. Go to https://dashboard.render.com
2. Click "New +" → "Web Service"
3. Connect your GitHub repo or upload code
4. Set these settings:
   - **Name**: bill-print-app (or your choice)
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`

5. Add Environment Variables:
   - `DATABASE_URL`: paste your Neon connection string
   - `FLASK_ENV`: production
   - `OUTPUT_DIR`: /tmp/output/bills

6. Click "Create Web Service"

### Option B: Deploy via Blueprint (render.yaml)

1. Push code to GitHub with `render.yaml` included
2. In Render dashboard: "New +" → "Blueprint"
3. Connect repo and deploy

## Step 3: Initialize Database

After first deploy, run this to create tables:

```bash
# In Render dashboard, go to your service
# Click "Shell" tab, then run:
python -c "from src.database import init_database; init_database()"
```

## Step 4: Test

1. Open your Render URL (e.g., https://bill-print-app.onrender.com)
2. Upload a CSV file
3. Check that PDFs are generated and downloaded

## Troubleshooting

### Database connection fails
- Check DATABASE_URL is correctly set in Render environment variables
- Ensure Neon DB allows connections from Render IPs

### Fonts missing
- Render uses Ubuntu, fonts should work
- If Tahoma missing, app falls back to Helvetica

### Out of memory
- Large CSVs may hit free tier limits
- Consider upgrading to paid plan or processing smaller batches

## Cost

- **Render**: Free tier (512 MB RAM, 0.1 CPU)
- **Neon**: Free tier (500 MB storage, 190 compute hours)
- **Total**: $0 for typical usage
</content>