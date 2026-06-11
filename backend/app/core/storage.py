"""
Storage abstraction so the rest of the app never cares where files live.

LocalStorage   -> writes to ./storage, served by FastAPI at /files/...
GCSStorage     -> uploads to a Google Cloud Storage bucket (the S3 equivalent)

Pick via env: STORAGE_BACKEND=local | gcs
Demo on local; flip to gcs for a public deploy with no code changes elsewhere.
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


def get_storage() -> Storage:
    backend = os.getenv("STORAGE_BACKEND", "local").lower()
    if backend == "gcs":
        bucket = os.getenv("GCS_BUCKET")
        if not bucket:
            raise RuntimeError("STORAGE_BACKEND=gcs but GCS_BUCKET is not set")
        return GCSStorage(bucket)
    return LocalStorage()


STORAGE = get_storage()
