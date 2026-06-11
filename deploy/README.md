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

## 5. (Recommended) HTTPS with Caddy — so the Amplify site can reach it

Your Amplify frontend is served over **https**, and browsers **block https→http**
calls. The fix: run the backend behind **Caddy**, which gets a free auto-renewing
Let's Encrypt cert. No domain purchase needed — we use **nip.io** (a hostname that
resolves to your IP).

In the EC2 **security group**, also open inbound **80** and **443** (from anywhere).

Then on the instance:
```bash
cd ~/zuno-content-pipeline/deploy
# turn your IP 13.235.1.2 into a dashed nip.io host:
echo "SITE_ADDRESS=13-235-1-2.nip.io" > caddy.env     # <-- use YOUR instance IP
docker compose up -d --build
```
Caddy provisions the cert in ~30s. Your API is now at:
```
https://13-235-1-2.nip.io
```

**Point the frontend at the HTTPS URL** — Amplify → Environment variables:
```
NEXT_PUBLIC_API_BASE = https://13-235-1-2.nip.io
```
Redeploy Amplify. Done — the live site reaches the backend over HTTPS.

> For a quick demo without HTTPS, you can skip Caddy and use
> `http://<INSTANCE_PUBLIC_IP>:8000` (run-backend.sh), but the Amplify site
> won't be able to call it from the browser — only a locally-run frontend will.

## Updating later
```bash
cd ~/zuno-content-pipeline && git pull
cd deploy && docker compose up -d --build     # if using Caddy/compose
# or: bash deploy/run-backend.sh               # if running the container directly
```
