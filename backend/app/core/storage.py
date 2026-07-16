"""
Storage abstraction so the rest of the app never cares where files live.

LocalStorage   -> writes to ./storage, served by FastAPI at /files/...
S3Storage      -> uploads to an AWS S3 bucket / access point

Pick via env: STORAGE_BACKEND=local | s3

The pipeline no longer renders images itself — it only lists what exists
(for the asset planner's dedup) — but save_image stays so an external
generation process can reuse the same abstraction.
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


def get_storage() -> Storage:
    backend = os.getenv("STORAGE_BACKEND", "local").lower()
    if backend == "s3":
        return S3Storage()
    return LocalStorage()


STORAGE = get_storage()
