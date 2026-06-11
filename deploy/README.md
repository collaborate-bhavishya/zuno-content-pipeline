# Deploying the backend on AWS EC2

The FastAPI + LangGraph backend runs as a Docker container on a small EC2 box.
Frontend stays on Amplify and points at this instance via `NEXT_PUBLIC_API_BASE`.

## 1. Launch the instance (AWS console)
- **EC2 → Launch instance**
- **AMI:** Amazon Linux 2023
- **Type:** `t3.micro` (free tier) — or `t3.small` (2 GB) if you hit memory limits
- **Key pair:** create/download one (for SSH)
- **Network → Security group**, allow inbound:
  - **SSH** TCP `22` from *My IP*
  - **Custom TCP** `8000` from `0.0.0.0/0` (so the frontend can reach the API)
- Launch.

## 2. SSH in and run setup
```bash
ssh -i your-key.pem ec2-user@<INSTANCE_PUBLIC_IP>
bash <(curl -s https://raw.githubusercontent.com/collaborate-bhavishya/zuno-content-pipeline/main/deploy/ec2-setup.sh)
exit            # log out/in so the docker group applies
ssh -i your-key.pem ec2-user@<INSTANCE_PUBLIC_IP>
```

## 3. Add secrets
Create `~/zuno-content-pipeline/backend/prod.env` (same values as your local `.env`):
```
ANTHROPIC_API_KEY=sk-ant-...
SUPABASE_URL=https://....supabase.co
SUPABASE_KEY=sb_publishable_...
S3_BUCKET=arn:aws:s3:ap-south-1:307506882879:accesspoint/content-pipeline
S3_PREFIX=
AWS_REGION=ap-south-1
GOOGLE_CLOUD_PROJECT=zunolearn
GOOGLE_CLOUD_LOCATION=us-central1
ADMIN_PASSWORD=change-me
STORAGE_BACKEND=local
```

**Google credentials** (for Gemini/Imagen) — copy your service-account JSON up:
```bash
# from your laptop:
scp -i your-key.pem ~/Downloads/zunolearn-e76b1cf1a085.json \
    ec2-user@<INSTANCE_PUBLIC_IP>:~/zuno-content-pipeline/backend/gcp-key.json
```
The run script auto-detects `backend/gcp-key.json` and mounts it.
(Alternatively, set `GOOGLE_API_KEY=` in prod.env and skip the JSON.)

**AWS creds for S3** — either attach an IAM role to the instance with
`s3:PutObject` on the access point (cleanest), or add `AWS_ACCESS_KEY_ID` /
`AWS_SECRET_ACCESS_KEY` to prod.env.

## 4. Build + run
```bash
bash ~/zuno-content-pipeline/deploy/run-backend.sh
curl http://localhost:8000/api/health        # should return ok
```
Visit `http://<INSTANCE_PUBLIC_IP>:8000/docs` from your browser to confirm.

## 5. Point the frontend at it
In **Amplify → Environment variables**:
```
NEXT_PUBLIC_API_BASE = http://<INSTANCE_PUBLIC_IP>:8000
```
Redeploy the Amplify frontend.

> ⚠️ Plain `http://` is fine for a demo. For production, put the instance behind
> an ALB or Caddy/Nginx with HTTPS (browsers block http calls from an https site).

## Updating later
```bash
cd ~/zuno-content-pipeline && git pull
bash deploy/run-backend.sh        # rebuilds + restarts
```
