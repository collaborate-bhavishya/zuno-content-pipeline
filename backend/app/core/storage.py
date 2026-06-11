"""
Storage abstraction so the rest of the app never cares where files live.

LocalStorage   -> writes to ./storage, served by FastAPI at /files/...
GCSStorage     -> uploads to a Google Cloud Storage bucket
S3Storage      -> uploads to an AWS S3 bucket / access point (images/ prefix)

Pick via env: STORAGE_BACKEND=local | gcs | s3
Demo on local; flip to s3/gcs for a durable deploy with no code changes elsewhere.
"""
import os
import io
from abc import ABC, abstractmethod
from PIL import Image


class Storage(ABC):
    @abstractmethod
    def save_image(self, pil_image: Image.Image, filename: str) -> str:
        """Persist a PIL image, return a URL the frontend can load."""

    @abstractmethod
    def exists(self, filename: str) -> bool:
        ...

    @abstractmethod
    def list_images(self) -> set:
        ...


class LocalStorage(Storage):
    def __init__(self, root: str = "storage", public_base: str = "/files"):
        self.root = os.path.abspath(root)
        self.img_dir = os.path.join(self.root, "images")
        os.makedirs(self.img_dir, exist_ok=True)
        self.public_base = public_base

    def save_image(self, pil_image: Image.Image, filename: str) -> str:
        path = os.path.join(self.img_dir, filename)
        pil_image.save(path, format="PNG")
        return f"{self.public_base}/images/{filename}"

    def exists(self, filename: str) -> bool:
        return os.path.exists(os.path.join(self.img_dir, filename))

    def list_images(self) -> set:
        return set(os.listdir(self.img_dir)) if os.path.isdir(self.img_dir) else set()

    def copy_image(self, src: str, dst: str) -> str:
        import shutil
        shutil.copy(os.path.join(self.img_dir, src), os.path.join(self.img_dir, dst))
        return f"{self.public_base}/images/{dst}"

    def delete_image(self, filename: str):
        p = os.path.join(self.img_dir, filename)
        if os.path.exists(p):
            os.remove(p)


class GCSStorage(Storage):
    """
    Google Cloud Storage — the Google equivalent of AWS S3.
    Needs: a GCP project, a bucket, and GOOGLE_APPLICATION_CREDENTIALS pointing
    at a service-account JSON (NOT Google Drive / OAuth).

      pip install google-cloud-storage
      export GCS_BUCKET=your-bucket
      export GOOGLE_APPLICATION_CREDENTIALS=/path/sa.json
    """
    def __init__(self, bucket_name: str):
        from google.cloud import storage as gcs  # imported lazily
        self.client = gcs.Client()
        self.bucket = self.client.bucket(bucket_name)
        self.prefix = "images/"

    def save_image(self, pil_image: Image.Image, filename: str) -> str:
        buf = io.BytesIO()
        pil_image.save(buf, format="PNG")
        buf.seek(0)
        blob = self.bucket.blob(self.prefix + filename)
        blob.upload_from_file(buf, content_type="image/png")
        # For public buckets:
        return blob.public_url

    def exists(self, filename: str) -> bool:
        return self.bucket.blob(self.prefix + filename).exists()

    def list_images(self) -> set:
        return {b.name.replace(self.prefix, "")
                for b in self.bucket.list_blobs(prefix=self.prefix)}

    def copy_image(self, src: str, dst: str) -> str:
        src_blob = self.bucket.blob(self.prefix + src)
        self.bucket.copy_blob(src_blob, self.bucket, self.prefix + dst)
        return self.bucket.blob(self.prefix + dst).public_url

    def delete_image(self, filename: str):
        self.bucket.blob(self.prefix + filename).delete()


class S3Storage(Storage):
    """AWS S3 (works with a plain bucket name OR an access-point ARN — same
    target used for run-JSON uploads). Images go under the 'images/' prefix.

    Env:
      S3_IMAGE_BUCKET       dedicated image bucket (falls back to S3_BUCKET)
      AWS_REGION            default ap-south-1
      S3_IMAGE_PREFIX       key prefix inside the bucket (default '' = root)
      S3_IMAGE_PUBLIC_BASE  full URL base used to SERVE images in a browser,
                            e.g. https://dxxxx.cloudfront.net  (if unset, built
                            from the bucket's public virtual-hosted URL)
      AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY  (or instance role)
    """
    def __init__(self):
        import boto3
        self.bucket = os.getenv("S3_IMAGE_BUCKET") or os.getenv("S3_BUCKET")
        if not self.bucket:
            raise RuntimeError("STORAGE_BACKEND=s3 but S3_IMAGE_BUCKET / S3_BUCKET is not set")
        self.region = os.getenv("AWS_REGION", "ap-south-1")
        self.prefix = os.getenv("S3_IMAGE_PREFIX", "").strip("/")
        base = os.getenv("S3_IMAGE_PUBLIC_BASE", "").rstrip("/")
        if not base:
            # Plain virtual-hosted bucket URL (requires public-read on the bucket).
            base = f"https://{self.bucket}.s3.{self.region}.amazonaws.com"
            if self.prefix:
                base = f"{base}/{self.prefix}"
        self.public_base = base
        kw = {"region_name": self.region}
        ak, sk = os.getenv("AWS_ACCESS_KEY_ID"), os.getenv("AWS_SECRET_ACCESS_KEY")
        if ak and sk:
            kw["aws_access_key_id"] = ak
            kw["aws_secret_access_key"] = sk
            if os.getenv("AWS_SESSION_TOKEN"):
                kw["aws_session_token"] = os.getenv("AWS_SESSION_TOKEN")
        self.s3 = boto3.session.Session(**kw).client("s3")

    def _key(self, filename: str) -> str:
        return f"{self.prefix}/{filename}" if self.prefix else filename

    def save_image(self, pil_image: Image.Image, filename: str) -> str:
        buf = io.BytesIO(); pil_image.save(buf, format="PNG"); buf.seek(0)
        self.s3.upload_fileobj(
            buf, self.bucket, self._key(filename),
            ExtraArgs={"ContentType": "image/png"})
        return f"{self.public_base}/{filename}"

    def exists(self, filename: str) -> bool:
        try:
            self.s3.head_object(Bucket=self.bucket, Key=self._key(filename))
            return True
        except Exception:
            return False

    def list_images(self) -> set:
        out = set()
        kw = {"Bucket": self.bucket}
        if self.prefix:
            kw["Prefix"] = self.prefix + "/"
        try:
            paginator = self.s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(**kw):
                for obj in page.get("Contents", []):
                    name = obj["Key"].split("/")[-1]
                    if name.endswith(".png"):
                        out.add(name)
        except Exception:
            pass
        return out

    def copy_image(self, src: str, dst: str) -> str:
        self.s3.copy_object(
            Bucket=self.bucket,
            CopySource={"Bucket": self.bucket, "Key": self._key(src)},
            Key=self._key(dst),
            ContentType="image/png", MetadataDirective="REPLACE")
        return f"{self.public_base}/{dst}"

    def delete_image(self, filename: str):
        self.s3.delete_object(Bucket=self.bucket, Key=self._key(filename))


def get_storage() -> Storage:
    backend = os.getenv("STORAGE_BACKEND", "local").lower()
    if backend == "gcs":
        bucket = os.getenv("GCS_BUCKET")
        if not bucket:
            raise RuntimeError("STORAGE_BACKEND=gcs but GCS_BUCKET is not set")
        return GCSStorage(bucket)
    if backend == "s3":
        return S3Storage()
    return LocalStorage()


STORAGE = get_storage()
